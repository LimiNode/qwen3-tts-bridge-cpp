#include <qwen_tts_bridge/client.hpp>
#include <qwen_tts_bridge/transport.hpp>

#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <evntprov.h>
#include <mmsystem.h>

#include <chrono>
#include <array>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE
#define QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE ""
#endif

#ifndef QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR
#define QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR ""
#endif

namespace {

using qwen_tts_bridge::AudioFormat;
using qwen_tts_bridge::PcmChunk;
using qwen_tts_bridge::QwenTtsClient;
using qwen_tts_bridge::QwenTtsClientOptions;
using qwen_tts_bridge::ReadyMessage;
using qwen_tts_bridge::RequestId;
using qwen_tts_bridge::StdIoTransportOptions;
using qwen_tts_bridge::TtsCallbacks;
using qwen_tts_bridge::TtsError;
using qwen_tts_bridge::TtsRequest;

struct ProgramOptions {
    bool help = false;
    bool use_mock_worker = false;
    std::string worker_executable;
    std::vector<std::string> worker_arguments;
    std::string working_directory;
    std::string text;
    std::string language = "auto";
    std::string speaker;
    std::string instruction;
    std::string voice_id;
    std::string reference_audio_path;
    std::string reference_text;
    bool x_vector_only = false;
    std::optional<double> temperature;
    std::optional<std::uint32_t> top_k;
    std::optional<double> top_p;
    std::optional<double> repetition_penalty;
    std::optional<bool> do_sample;
    std::optional<std::uint64_t> seed;
    bool sampling_overrides_supported = false;
    bool deterministic_seed_supported = false;
    bool voice_clone_supported = false;
    bool voice_profiles_supported = false;
    std::vector<std::string> voice_ids;
    std::uint32_t sample_rate = 24000;
    std::uint32_t channels = 1;
    int mock_chunks = 3;
    int mock_chunk_ms = 100;
    double mock_chunk_delay = 0.0;
    std::chrono::milliseconds startup_timeout{30000};
    std::string playback_metrics_file;
    bool etw_playback_markers = false;
};

class ConsoleCodePageGuard final {
public:
    ConsoleCodePageGuard()
        : input_code_page_(GetConsoleCP()),
          output_code_page_(GetConsoleOutputCP()) {
        if (input_code_page_ != 0) {
            SetConsoleCP(CP_UTF8);
        }
        if (output_code_page_ != 0) {
            SetConsoleOutputCP(CP_UTF8);
        }
    }

    ~ConsoleCodePageGuard() {
        if (input_code_page_ != 0) {
            SetConsoleCP(input_code_page_);
        }
        if (output_code_page_ != 0) {
            SetConsoleOutputCP(output_code_page_);
        }
    }

    ConsoleCodePageGuard(const ConsoleCodePageGuard&) = delete;
    ConsoleCodePageGuard& operator=(const ConsoleCodePageGuard&) = delete;

private:
    UINT input_code_page_ = 0;
    UINT output_code_page_ = 0;
};

struct PlaybackChunkMetric {
    double arrival_ms = 0.0;
    std::optional<double> inter_arrival_ms;
    double audio_duration_ms = 0.0;
    double queued_audio_before_ms = 0.0;
    double queued_audio_after_ms = 0.0;
    bool queue_empty_before_later_chunk = false;
};

class EtwPlaybackMarkers final {
public:
    EtwPlaybackMarkers() {
        const ULONG result = EventRegister(&provider_id(), nullptr, nullptr, &registration_);
        if (result != ERROR_SUCCESS) {
            throw std::runtime_error("failed to register playback ETW marker provider");
        }
    }

    ~EtwPlaybackMarkers() {
        if (registration_ != 0) {
            EventUnregister(registration_);
        }
    }

    EtwPlaybackMarkers(const EtwPlaybackMarkers&) = delete;
    EtwPlaybackMarkers& operator=(const EtwPlaybackMarkers&) = delete;

    void request_start() const {
        write(L"qwen_tts_bridge.playback.request_start");
    }

    void queue_empty_before_later_chunk(std::size_t chunk_index) const {
        write(
            L"qwen_tts_bridge.playback.queue_empty_before_later_chunk index=" +
            std::to_wstring(chunk_index));
    }

private:
    static const GUID& provider_id() {
        static const GUID value{
            0x9f07e68d,
            0x2b7a,
            0x4bc1,
            {0xa5, 0x8d, 0x95, 0x62, 0x4f, 0x0d, 0x6f, 0xe6}};
        return value;
    }

    void write(const std::wstring& marker) const {
        const ULONG result = EventWriteString(registration_, 0, 0, marker.c_str());
        if (result != ERROR_SUCCESS) {
            throw std::runtime_error("failed to write playback ETW marker");
        }
    }

    REGHANDLE registration_ = 0;
};

class PlaybackMetrics final {
public:
    explicit PlaybackMetrics(EtwPlaybackMarkers* etw_markers = nullptr)
        : etw_markers_(etw_markers) {
    }

    void begin_request() {
        std::lock_guard<std::mutex> lock(mutex_);
        started_at_ = std::chrono::steady_clock::now();
        chunks_.clear();
        playback_completed_ = false;
        if (etw_markers_ != nullptr) {
            etw_markers_->request_start();
        }
    }

    void record_chunk(
        double audio_duration_ms,
        double queued_audio_before_ms,
        double queued_audio_after_ms,
        bool queue_empty_before_later_chunk) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!started_at_.has_value()) {
            return;
        }

        const auto now = std::chrono::steady_clock::now();
        const double arrival_ms = elapsed_ms(started_at_.value(), now);
        PlaybackChunkMetric metric;
        metric.arrival_ms = arrival_ms;
        metric.audio_duration_ms = audio_duration_ms;
        metric.queued_audio_before_ms = queued_audio_before_ms;
        metric.queued_audio_after_ms = queued_audio_after_ms;
        metric.queue_empty_before_later_chunk = queue_empty_before_later_chunk;
        if (!chunks_.empty()) {
            metric.inter_arrival_ms = arrival_ms - chunks_.back().arrival_ms;
        }
        chunks_.push_back(metric);
        if (queue_empty_before_later_chunk && etw_markers_ != nullptr) {
            etw_markers_->queue_empty_before_later_chunk(chunks_.size() - 1);
        }
    }

    void mark_playback_completed() {
        std::lock_guard<std::mutex> lock(mutex_);
        playback_completed_ = true;
    }

    void write_json_file(const std::string& file_name) const {
        std::vector<PlaybackChunkMetric> chunks;
        bool playback_completed = false;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            if (!started_at_.has_value()) {
                throw std::runtime_error("playback metrics were not started");
            }
            chunks = chunks_;
            playback_completed = playback_completed_;
        }

        std::size_t queue_empty_before_later_chunk_count = 0;
        double total_audio_duration_ms = 0.0;
        for (const PlaybackChunkMetric& chunk : chunks) {
            total_audio_duration_ms += chunk.audio_duration_ms;
            if (chunk.queue_empty_before_later_chunk) {
                ++queue_empty_before_later_chunk_count;
            }
        }

        std::ostringstream json;
        json << std::fixed << std::setprecision(3);
        json << "{\n"
             << "  \"schema_version\": 1,\n"
             << "  \"measurement\": \"waveout_queue_starvation_proxy\",\n"
             << "  \"etw_playback_markers_enabled\": "
             << (etw_markers_ != nullptr ? "true" : "false") << ",\n"
             << "  \"playback_completed\": " << (playback_completed ? "true" : "false") << ",\n"
             << "  \"audio_chunk_count\": " << chunks.size() << ",\n"
             << "  \"total_audio_duration_ms\": " << total_audio_duration_ms << ",\n"
             << "  \"queue_empty_before_later_chunk_count\": "
             << queue_empty_before_later_chunk_count << ",\n"
             << "  \"chunks\": [\n";
        for (std::size_t index = 0; index < chunks.size(); ++index) {
            const PlaybackChunkMetric& chunk = chunks[index];
            json << "    {\"arrival_ms\": " << chunk.arrival_ms << ", \"inter_arrival_ms\": ";
            if (chunk.inter_arrival_ms.has_value()) {
                json << chunk.inter_arrival_ms.value();
            }
            else {
                json << "null";
            }
            json << ", \"audio_duration_ms\": " << chunk.audio_duration_ms
                 << ", \"queued_audio_before_ms\": " << chunk.queued_audio_before_ms
                 << ", \"queued_audio_after_ms\": " << chunk.queued_audio_after_ms
                 << ", \"queue_empty_before_later_chunk\": "
                 << (chunk.queue_empty_before_later_chunk ? "true" : "false") << "}";
            if (index + 1 != chunks.size()) {
                json << ',';
            }
            json << '\n';
        }
        json << "  ]\n}\n";

        const std::filesystem::path target = std::filesystem::u8path(file_name);
        if (std::filesystem::exists(target)) {
            throw std::runtime_error("refusing to overwrite existing playback metrics file: " + file_name);
        }
        const std::filesystem::path temporary =
            std::filesystem::path(
                target.native() + L".tmp." + std::to_wstring(GetCurrentProcessId()));
        try {
            std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
            if (!output) {
                throw std::runtime_error("failed to open playback metrics file: " + temporary.string());
            }
            output << json.str();
            output.close();
            if (!output) {
                throw std::runtime_error("failed to write playback metrics file: " + temporary.string());
            }
            std::filesystem::rename(temporary, target);
        }
        catch (...) {
            std::error_code ignored;
            std::filesystem::remove(temporary, ignored);
            throw;
        }
    }

private:
    static double elapsed_ms(
        std::chrono::steady_clock::time_point start,
        std::chrono::steady_clock::time_point end) {
        return std::chrono::duration<double, std::milli>(end - start).count();
    }

    mutable std::mutex mutex_;
    std::optional<std::chrono::steady_clock::time_point> started_at_;
    std::vector<PlaybackChunkMetric> chunks_;
    bool playback_completed_ = false;
    EtwPlaybackMarkers* etw_markers_ = nullptr;
};

class WaveOutPlayer final {
public:
    explicit WaveOutPlayer(PlaybackMetrics* metrics = nullptr)
        : metrics_(metrics) {
    }

    ~WaveOutPlayer() {
        close_noexcept();
    }

    WaveOutPlayer(const WaveOutPlayer&) = delete;
    WaveOutPlayer& operator=(const WaveOutPlayer&) = delete;

    void enqueue(std::uint64_t playback_epoch, const PcmChunk& chunk) {
        if (chunk.format.sample_format != "s16le") {
            throw std::runtime_error("default-device playback requires s16le PCM");
        }
        if (chunk.format.sample_rate == 0 ||
            chunk.format.channels == 0 ||
            chunk.format.channels > std::numeric_limits<WORD>::max()) {
            throw std::runtime_error("invalid PCM format for default-device playback");
        }
        if (chunk.bytes.empty()) {
            return;
        }

        std::lock_guard<std::mutex> lock(mutex_);
        if (playback_epoch != playback_epoch_) {
            return;
        }
        reap_finished_locked();
        open_or_validate_locked(chunk.format);
        const double queued_audio_before_ms = queued_audio_duration_ms_locked();
        const bool queue_empty_before_later_chunk =
            has_enqueued_audio_since_reset_ && buffers_.empty();

        auto buffer = std::make_unique<Buffer>();
        buffer->bytes = chunk.bytes;
        buffer->header.lpData = reinterpret_cast<LPSTR>(buffer->bytes.data());
        buffer->header.dwBufferLength = static_cast<DWORD>(buffer->bytes.size());
        buffer->duration_ms = pcm_duration_ms(chunk.format, buffer->bytes.size());

        check_mmresult(
            waveOutPrepareHeader(m_handle, &buffer->header, sizeof(WAVEHDR)),
            "waveOutPrepareHeader");
        buffer->prepared = true;
        try {
            check_mmresult(
                waveOutWrite(m_handle, &buffer->header, sizeof(WAVEHDR)),
                "waveOutWrite");
        }
        catch (...) {
            waveOutUnprepareHeader(m_handle, &buffer->header, sizeof(WAVEHDR));
            throw;
        }
        buffers_.push_back(std::move(buffer));
        has_enqueued_audio_since_reset_ = true;
        if (metrics_ != nullptr) {
            metrics_->record_chunk(
                pcm_duration_ms(chunk.format, chunk.bytes.size()),
                queued_audio_before_ms,
                queued_audio_duration_ms_locked(),
                queue_empty_before_later_chunk);
        }
    }

    /// Stops queued and currently playing audio, invalidating prior callback epochs.
    /// It never cancels worker inference.
    [[nodiscard]] std::uint64_t reset() {
        std::unique_lock<std::mutex> lock(mutex_);
        ++playback_epoch_;
        if (playback_epoch_ == 0) {
            ++playback_epoch_;
        }
        if (m_handle == nullptr) {
            has_enqueued_audio_since_reset_ = false;
            return playback_epoch_;
        }

        check_mmresult(waveOutReset(m_handle), "waveOutReset");
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
        while (!buffers_.empty()) {
            reap_finished_locked();
            if (buffers_.empty()) {
                break;
            }
            if (std::chrono::steady_clock::now() >= deadline) {
                throw std::runtime_error("timed out waiting for default audio device reset");
            }
            lock.unlock();
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
            lock.lock();
        }
        has_enqueued_audio_since_reset_ = false;
        return playback_epoch_;
    }

    void wait_until_idle(std::chrono::milliseconds timeout) {
        std::unique_lock<std::mutex> lock(mutex_);
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (!buffers_.empty()) {
            reap_finished_locked();
            if (buffers_.empty()) {
                return;
            }
            if (std::chrono::steady_clock::now() >= deadline) {
                throw std::runtime_error("timed out waiting for default audio playback");
            }
            lock.unlock();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            lock.lock();
        }
    }

private:
    struct Buffer {
        std::vector<std::byte> bytes;
        WAVEHDR header{};
        bool prepared = false;
        double duration_ms = 0.0;
    };

    static bool formats_match(const AudioFormat& left, const AudioFormat& right) {
        return left.sample_format == right.sample_format &&
            left.sample_rate == right.sample_rate &&
            left.channels == right.channels;
    }

    static void check_mmresult(MMRESULT result, const char* operation) {
        if (result == MMSYSERR_NOERROR) {
            return;
        }
        char message[MAXERRORLENGTH]{};
        waveOutGetErrorTextA(result, message, static_cast<UINT>(sizeof(message)));
        throw std::runtime_error(std::string(operation) + " failed: " + message);
    }

    static double pcm_duration_ms(const AudioFormat& format, std::size_t byte_count) {
        const std::uint64_t bytes_per_second =
            static_cast<std::uint64_t>(format.sample_rate) * format.channels * sizeof(std::int16_t);
        if (bytes_per_second == 0) {
            throw std::runtime_error("invalid PCM format for duration measurement");
        }
        return static_cast<double>(byte_count) * 1000.0 /
            static_cast<double>(bytes_per_second);
    }

    double queued_audio_duration_ms_locked() const {
        double duration_ms = 0.0;
        for (const std::unique_ptr<Buffer>& buffer : buffers_) {
            duration_ms += buffer->duration_ms;
        }
        return duration_ms;
    }

    void open_or_validate_locked(const AudioFormat& format) {
        if (m_handle != nullptr) {
            if (!formats_match(m_format, format)) {
                throw std::runtime_error(
                    "default-device playback cannot change PCM format while audio is queued");
            }
            return;
        }

        WAVEFORMATEX wave_format{};
        wave_format.wFormatTag = WAVE_FORMAT_PCM;
        wave_format.nChannels = static_cast<WORD>(format.channels);
        wave_format.nSamplesPerSec = format.sample_rate;
        wave_format.wBitsPerSample = 16;
        wave_format.nBlockAlign = static_cast<WORD>(
            wave_format.nChannels * (wave_format.wBitsPerSample / 8));
        wave_format.nAvgBytesPerSec = wave_format.nSamplesPerSec * wave_format.nBlockAlign;

        check_mmresult(
            waveOutOpen(&m_handle, WAVE_MAPPER, &wave_format, 0, 0, CALLBACK_NULL),
            "waveOutOpen");
        m_format = format;
    }

    void reap_finished_locked() {
        for (auto it = buffers_.begin(); it != buffers_.end();) {
            Buffer& buffer = **it;
            if ((buffer.header.dwFlags & WHDR_DONE) == 0) {
                ++it;
                continue;
            }
            if (buffer.prepared) {
                check_mmresult(
                    waveOutUnprepareHeader(m_handle, &buffer.header, sizeof(WAVEHDR)),
                    "waveOutUnprepareHeader");
                buffer.prepared = false;
            }
            it = buffers_.erase(it);
        }
    }

    void close_noexcept() noexcept {
        try {
            static_cast<void>(reset());
        }
        catch (...) {
        }

        std::lock_guard<std::mutex> lock(mutex_);
        if (m_handle != nullptr) {
            waveOutClose(m_handle);
            m_handle = nullptr;
        }
    }

    std::mutex mutex_;
    HWAVEOUT m_handle = nullptr;
    AudioFormat m_format;
    std::vector<std::unique_ptr<Buffer>> buffers_;
    std::uint64_t playback_epoch_ = 1;
    bool has_enqueued_audio_since_reset_ = false;
    PlaybackMetrics* metrics_ = nullptr;
};

struct ActiveRequestState {
    std::mutex mutex;
    RequestId active_request_id = 0;
    RequestId next_request_id = 1;
};

struct OneShotState {
    std::mutex mutex;
    std::condition_variable condition;
    bool terminal = false;
    bool success = false;
    std::string message;
};

std::string utf8_from_wide(const std::wstring& value);

void print_usage(std::ostream& out, const std::string& executable_name) {
    out << "Usage:\n"
        << "  " << executable_name << " --mock [--speaker name]\n"
        << "  " << executable_name << " --worker qwen_tts_worker.exe [--speaker name]\n"
        << "  " << executable_name << " --worker qwen_tts_worker.exe --text \"Hello\"\n\n"
        << "Interactive commands:\n"
        << "  <text>                 Cancel current generation and speak this text.\n"
        << "  /cancel                Cancel current generation and stop playback.\n"
        << "  /voice <name>          Select a registered profile, or a CustomVoice speaker.\n"
        << "  /voices                 List registered Base voice profiles.\n"
        << "  /language <name>       Set the language for future requests.\n"
        << "  /style <text>          Set the style instruction for future requests.\n"
        << "  /temperature <value|default>  Set sampling temperature for future requests.\n"
        << "  /top-k <value|default> Set top-k candidate limit for future requests.\n"
        << "  /top-p <value|default> Set nucleus probability for future requests.\n"
        << "  /repetition-penalty <value|default> Set repetition penalty for future requests.\n"
        << "  /sample <on|off|default> Set sampling mode for future requests.\n"
        << "  /seed <value|default>  Set deterministic seed for future requests.\n"
        << "  /sampling               Show current per-request sampling controls.\n"
        << "  --etw-playback-markers  Emit ETW request and queue-starvation markers (diagnostic).\n"
        << "  /help                  Show this help.\n"
        << "  /quit                  Stop the worker and exit.\n\n"
        << "Options:\n"
        << "  --help                         Show this help.\n"
        << "  --mock                         Run the bundled Python mock worker.\n"
        << "  --worker <path>                Worker executable path.\n"
        << "  --worker-arg <arg>             Extra worker argument; may be repeated.\n"
        << "  --cwd <path>                   Worker working directory.\n"
        << "  --text <utf8>                  One-shot playback instead of interactive mode.\n"
        << "  --language <name>              Request language, default: auto.\n"
        << "  --speaker <name>               Optional request speaker or voice name.\n"
        << "  --voice-id <name>              Registered Base voice profile identifier.\n"
        << "  --instruction <utf8>           Natural-language style instruction.\n"
        << "  --reference-audio <path>       Local WAV reference for Base voice cloning.\n"
        << "  --reference-text <utf8>        Transcript of the reference audio.\n"
        << "  --x-vector-only                Clone speaker embedding without transcript.\n"
        << "  --temperature <value>          Per-request sampling temperature.\n"
        << "  --top-k <value>                Per-request top-k candidate limit.\n"
        << "  --top-p <value>                Per-request nucleus probability.\n"
        << "  --repetition-penalty <value>   Per-request repetition penalty.\n"
        << "  --sample                       Enable per-request sampling.\n"
        << "  --no-sample                    Use per-request greedy decoding.\n"
        << "  --seed <value>                 Per-request deterministic seed.\n"
        << "  --sample-rate <hz>             Requested sample rate, default: 24000.\n"
        << "  --channels <count>             Requested channel count, default: 1.\n"
        << "  --startup-timeout-ms <ms>      Worker startup timeout, default: 30000.\n"
        << "  --playback-metrics-file <path> Write opt-in one-shot WaveOut queue metrics JSON.\n"
        << "  --mock-chunks <count>          Mock worker chunk count, default: 3.\n"
        << "  --mock-chunk-ms <ms>           Mock chunk duration, default: 100.\n"
        << "  --mock-chunk-delay <seconds>   Mock delay between chunks, default: 0.\n";
}

std::string require_value(
    int& index,
    int argc,
    wchar_t** argv,
    const std::string& option) {
    const std::string prefix = option + '=';
    const std::string current = utf8_from_wide(argv[index]);
    if (current.rfind(prefix, 0) == 0) {
        return current.substr(prefix.size());
    }
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value for " + option);
    }
    ++index;
    return utf8_from_wide(argv[index]);
}

std::uint32_t parse_u32(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const unsigned long result = std::stoul(value, &parsed, 10);
    if (parsed != value.size() || result > std::numeric_limits<std::uint32_t>::max()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<std::uint32_t>(result);
}

std::uint64_t parse_u64(const std::string& value, const std::string& option) {
    if (value.empty() || value.front() == '-') {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    std::size_t parsed = 0;
    const unsigned long long result = std::stoull(value, &parsed, 10);
    if (parsed != value.size()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<std::uint64_t>(result);
}

int parse_int(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const long result = std::stol(value, &parsed, 10);
    if (parsed != value.size() || result < (std::numeric_limits<int>::min)() ||
        result > (std::numeric_limits<int>::max)()) {
        throw std::runtime_error("invalid integer for " + option + ": " + value);
    }
    return static_cast<int>(result);
}

double parse_double(const std::string& value, const std::string& option) {
    std::size_t parsed = 0;
    const double result = std::stod(value, &parsed);
    if (parsed != value.size() || !std::isfinite(result)) {
        throw std::runtime_error("invalid number for " + option + ": " + value);
    }
    return result;
}

ProgramOptions parse_options(int argc, wchar_t** argv) {
    ProgramOptions options;
    for (int index = 1; index < argc; ++index) {
        const std::string arg = utf8_from_wide(argv[index]);
        if (arg == "--help" || arg == "-h") {
            options.help = true;
        }
        else if (arg == "--mock") {
            options.use_mock_worker = true;
        }
        else if (arg == "--worker" || arg.rfind("--worker=", 0) == 0) {
            options.worker_executable = require_value(index, argc, argv, "--worker");
        }
        else if (arg == "--worker-arg" || arg.rfind("--worker-arg=", 0) == 0) {
            options.worker_arguments.push_back(
                require_value(index, argc, argv, "--worker-arg"));
        }
        else if (arg == "--cwd" || arg.rfind("--cwd=", 0) == 0) {
            options.working_directory = require_value(index, argc, argv, "--cwd");
        }
        else if (arg == "--text" || arg.rfind("--text=", 0) == 0) {
            options.text = require_value(index, argc, argv, "--text");
        }
        else if (arg == "--language" || arg.rfind("--language=", 0) == 0) {
            options.language = require_value(index, argc, argv, "--language");
        }
        else if (arg == "--speaker" || arg.rfind("--speaker=", 0) == 0) {
            options.speaker = require_value(index, argc, argv, "--speaker");
        }
        else if (arg == "--instruction" || arg.rfind("--instruction=", 0) == 0) {
            options.instruction = require_value(index, argc, argv, "--instruction");
        }
        else if (arg == "--voice-id" || arg.rfind("--voice-id=", 0) == 0) {
            options.voice_id = require_value(index, argc, argv, "--voice-id");
        }
        else if (arg == "--reference-audio" || arg.rfind("--reference-audio=", 0) == 0) {
            options.reference_audio_path = require_value(index, argc, argv, "--reference-audio");
        }
        else if (arg == "--reference-text" || arg.rfind("--reference-text=", 0) == 0) {
            options.reference_text = require_value(index, argc, argv, "--reference-text");
        }
        else if (arg == "--x-vector-only") {
            options.x_vector_only = true;
        }
        else if (arg == "--temperature" || arg.rfind("--temperature=", 0) == 0) {
            options.temperature = parse_double(
                require_value(index, argc, argv, "--temperature"), "--temperature");
        }
        else if (arg == "--top-k" || arg.rfind("--top-k=", 0) == 0) {
            options.top_k = parse_u32(
                require_value(index, argc, argv, "--top-k"), "--top-k");
        }
        else if (arg == "--top-p" || arg.rfind("--top-p=", 0) == 0) {
            options.top_p = parse_double(
                require_value(index, argc, argv, "--top-p"), "--top-p");
        }
        else if (arg == "--repetition-penalty" ||
                 arg.rfind("--repetition-penalty=", 0) == 0) {
            options.repetition_penalty = parse_double(
                require_value(index, argc, argv, "--repetition-penalty"),
                "--repetition-penalty");
        }
        else if (arg == "--sample") {
            options.do_sample = true;
        }
        else if (arg == "--no-sample") {
            options.do_sample = false;
        }
        else if (arg == "--seed" || arg.rfind("--seed=", 0) == 0) {
            options.seed = parse_u64(
                require_value(index, argc, argv, "--seed"), "--seed");
        }
        else if (arg == "--sample-rate" || arg.rfind("--sample-rate=", 0) == 0) {
            options.sample_rate = parse_u32(
                require_value(index, argc, argv, "--sample-rate"), "--sample-rate");
        }
        else if (arg == "--channels" || arg.rfind("--channels=", 0) == 0) {
            options.channels = parse_u32(
                require_value(index, argc, argv, "--channels"), "--channels");
        }
        else if (arg == "--startup-timeout-ms" ||
                 arg.rfind("--startup-timeout-ms=", 0) == 0) {
            options.startup_timeout = std::chrono::milliseconds(parse_u32(
                require_value(index, argc, argv, "--startup-timeout-ms"),
                "--startup-timeout-ms"));
        }
        else if (arg == "--playback-metrics-file" ||
                 arg.rfind("--playback-metrics-file=", 0) == 0) {
            options.playback_metrics_file = require_value(
                index, argc, argv, "--playback-metrics-file");
        }
        else if (arg == "--etw-playback-markers") {
            options.etw_playback_markers = true;
        }
        else if (arg == "--mock-chunks" || arg.rfind("--mock-chunks=", 0) == 0) {
            options.mock_chunks = parse_int(
                require_value(index, argc, argv, "--mock-chunks"), "--mock-chunks");
        }
        else if (arg == "--mock-chunk-ms" || arg.rfind("--mock-chunk-ms=", 0) == 0) {
            options.mock_chunk_ms = parse_int(
                require_value(index, argc, argv, "--mock-chunk-ms"), "--mock-chunk-ms");
        }
        else if (arg == "--mock-chunk-delay" ||
                 arg.rfind("--mock-chunk-delay=", 0) == 0) {
            options.mock_chunk_delay = parse_double(
                require_value(index, argc, argv, "--mock-chunk-delay"),
                "--mock-chunk-delay");
        }
        else {
            throw std::runtime_error("unknown option: " + arg);
        }
    }
    return options;
}

void validate_options(const ProgramOptions& options) {
    if (options.help) {
        return;
    }
    if (!options.use_mock_worker && options.worker_executable.empty()) {
        throw std::runtime_error("--worker is required unless --mock is used");
    }
    if (options.sample_rate == 0 || options.channels == 0 ||
        options.channels > (std::numeric_limits<WORD>::max)()) {
        throw std::runtime_error("invalid requested PCM format");
    }
    if (options.mock_chunks <= 0 || options.mock_chunk_ms <= 0 ||
        options.mock_chunk_delay < 0.0) {
        throw std::runtime_error("invalid mock worker options");
    }
    if (options.etw_playback_markers && options.playback_metrics_file.empty()) {
        throw std::runtime_error("--etw-playback-markers requires --playback-metrics-file");
    }
    if (options.temperature.has_value() &&
        (options.temperature.value() <= 0.0 || options.temperature.value() > 2.0)) {
        throw std::runtime_error("--temperature must be in the interval (0, 2]");
    }
    if (options.top_k.has_value() && options.top_k.value() == 0) {
        throw std::runtime_error("--top-k must be greater than zero");
    }
    if (options.top_p.has_value() &&
        (options.top_p.value() <= 0.0 || options.top_p.value() > 1.0)) {
        throw std::runtime_error("--top-p must be in the interval (0, 1]");
    }
    if (options.repetition_penalty.has_value() &&
        (options.repetition_penalty.value() < 1.0 ||
         options.repetition_penalty.value() > 2.0)) {
        throw std::runtime_error("--repetition-penalty must be in the interval [1, 2]");
    }
    if (options.reference_audio_path.empty() &&
        (!options.reference_text.empty() || options.x_vector_only)) {
        throw std::runtime_error("--reference-text and --x-vector-only require --reference-audio");
    }
    if (!options.reference_audio_path.empty() &&
        options.reference_text.empty() && !options.x_vector_only) {
        throw std::runtime_error(
            "--reference-audio requires --reference-text unless --x-vector-only is set");
    }
    if (!options.voice_id.empty() &&
        (!options.reference_audio_path.empty() || !options.reference_text.empty() ||
         options.x_vector_only)) {
        throw std::runtime_error(
            "--voice-id cannot be combined with direct reference-audio options");
    }
    if (!options.playback_metrics_file.empty() && options.text.empty()) {
        throw std::runtime_error("--playback-metrics-file requires one-shot --text playback");
    }
}

StdIoTransportOptions make_transport_options(const ProgramOptions& options) {
    StdIoTransportOptions transport_options;
    transport_options.stderr_handler = [](std::string text) {
        std::cerr << text;
    };
    if (options.use_mock_worker) {
        const std::string python_executable = QWEN_TTS_BRIDGE_EXAMPLE_PYTHON_EXECUTABLE;
        const std::string worker_dir = QWEN_TTS_BRIDGE_EXAMPLE_WORKER_DIR;
        if (python_executable.empty() || worker_dir.empty()) {
            throw std::runtime_error("--mock is unavailable because Python was not found at build time");
        }
        transport_options.arguments = {
            python_executable,
            "-m",
            "qwen_tts_bridge_worker.main",
            "--mock",
            "--mock-chunks",
            std::to_string(options.mock_chunks),
            "--mock-chunk-ms",
            std::to_string(options.mock_chunk_ms),
            "--mock-chunk-delay",
            std::to_string(options.mock_chunk_delay)
        };
        transport_options.working_directory = worker_dir;
        return transport_options;
    }

    transport_options.arguments.push_back(options.worker_executable);
    transport_options.arguments.insert(
        transport_options.arguments.end(),
        options.worker_arguments.begin(),
        options.worker_arguments.end());
    transport_options.working_directory = options.working_directory;
    return transport_options;
}

AudioFormat requested_audio_format(const ProgramOptions& options) {
    AudioFormat format;
    format.sample_format = "s16le";
    format.sample_rate = options.sample_rate;
    format.channels = options.channels;
    return format;
}

bool is_active_request(ActiveRequestState& state, RequestId request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.active_request_id == request_id;
}

void clear_active_request(ActiveRequestState& state, RequestId request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (state.active_request_id == request_id) {
        state.active_request_id = 0;
    }
}

std::uint64_t cancel_active_request(
    QwenTtsClient& client,
    WaveOutPlayer& player,
    ActiveRequestState& state) {
    RequestId request_id = 0;
    {
        std::lock_guard<std::mutex> lock(state.mutex);
        request_id = state.active_request_id;
        state.active_request_id = 0;
    }
    if (request_id != 0) {
        client.cancel(request_id);
    }
    return player.reset();
}

RequestId submit_request(
    QwenTtsClient& client,
    WaveOutPlayer& player,
    ActiveRequestState& active_state,
    const ProgramOptions& options,
    const std::string& text,
    OneShotState* one_shot_state = nullptr) {
    const std::uint64_t playback_epoch =
        cancel_active_request(client, player, active_state);

    TtsRequest request;
    request.text = text;
    request.language = options.language;
    request.speaker = options.speaker;
    request.instruction = options.instruction;
    request.voice_id = options.voice_id;
    request.reference_audio_path = options.reference_audio_path;
    request.reference_text = options.reference_text;
    request.x_vector_only = options.x_vector_only;
    request.sampling.temperature = options.temperature;
    request.sampling.top_k = options.top_k;
    request.sampling.top_p = options.top_p;
    request.sampling.repetition_penalty = options.repetition_penalty;
    request.sampling.do_sample = options.do_sample;
    if (options.seed.has_value()) {
        request.has_seed = true;
        request.seed = options.seed.value();
    }
    request.output = requested_audio_format(options);
    {
        std::lock_guard<std::mutex> lock(active_state.mutex);
        request.id = active_state.next_request_id++;
        if (request.id == 0) {
            request.id = active_state.next_request_id++;
        }
        active_state.active_request_id = request.id;
    }

    const RequestId request_id = request.id;
    TtsCallbacks callbacks;
    callbacks.on_audio = [&player, &active_state, playback_epoch, request_id](const PcmChunk& chunk) {
        if (!is_active_request(active_state, request_id)) {
            return;
        }
        try {
            player.enqueue(playback_epoch, chunk);
        }
        catch (const std::exception& exc) {
            std::cerr << "playback error: " << exc.what() << '\n';
        }
    };
    callbacks.on_completed = [&active_state, one_shot_state, request_id] {
        clear_active_request(active_state, request_id);
        if (one_shot_state != nullptr) {
            std::lock_guard<std::mutex> lock(one_shot_state->mutex);
            one_shot_state->terminal = true;
            one_shot_state->success = true;
            one_shot_state->condition.notify_all();
        }
        else {
            std::cout << "completed request " << request_id << '\n';
        }
    };
    callbacks.on_cancelled = [&player, &active_state, one_shot_state, request_id] {
        if (is_active_request(active_state, request_id)) {
            static_cast<void>(player.reset());
            clear_active_request(active_state, request_id);
        }
        if (one_shot_state != nullptr) {
            std::lock_guard<std::mutex> lock(one_shot_state->mutex);
            one_shot_state->terminal = true;
            one_shot_state->message = "request cancelled";
            one_shot_state->condition.notify_all();
        }
    };
    callbacks.on_error = [&player, &active_state, one_shot_state, request_id](const TtsError& error) {
        if (is_active_request(active_state, request_id)) {
            static_cast<void>(player.reset());
            clear_active_request(active_state, request_id);
        }
        if (one_shot_state != nullptr) {
            std::lock_guard<std::mutex> lock(one_shot_state->mutex);
            one_shot_state->terminal = true;
            one_shot_state->message = error.category + "/" + error.code + ": " + error.message;
            one_shot_state->condition.notify_all();
        }
        else {
            std::cerr << "request " << request_id << " failed: " << error.category
                      << '/' << error.code << ": " << error.message << '\n';
        }
    };

    if (client.synthesize_async(std::move(request), std::move(callbacks)) != request_id) {
        clear_active_request(active_state, request_id);
        throw std::runtime_error("failed to enqueue synthesis request");
    }
    return request_id;
}

bool wait_for_one_shot(OneShotState& state, std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(state.mutex);
    return state.condition.wait_for(lock, timeout, [&state] { return state.terminal; });
}

void print_interactive_status(const ProgramOptions& options) {
    std::cout << "speaker=" << (options.speaker.empty() ? "<worker default>" : options.speaker)
              << ", voice_id=" << (options.voice_id.empty() ? "<none>" : options.voice_id)
              << ", language=" << options.language
              << ", style=" << (options.instruction.empty() ? "<none>" : options.instruction)
              << "\n";
    std::cout << "sampling: temperature="
              << (options.temperature.has_value() ? std::to_string(options.temperature.value()) : "<worker default>")
              << ", top_k="
              << (options.top_k.has_value() ? std::to_string(options.top_k.value()) : "<worker default>")
              << ", top_p="
              << (options.top_p.has_value() ? std::to_string(options.top_p.value()) : "<worker default>")
              << ", repetition_penalty="
              << (options.repetition_penalty.has_value() ? std::to_string(options.repetition_penalty.value()) : "<worker default>")
              << ", do_sample=";
    if (!options.do_sample.has_value()) {
        std::cout << "<worker default>";
    }
    else {
        std::cout << (options.do_sample.value() ? "on" : "off");
    }
    std::cout << ", seed="
              << (options.seed.has_value() ? std::to_string(options.seed.value()) : "<worker default>")
              << '\n';
    std::cout << "worker capabilities: sampling_overrides="
              << (options.sampling_overrides_supported ? "true" : "false")
              << ", deterministic_seed="
              << (options.deterministic_seed_supported ? "true" : "false")
              << ", voice_clone="
              << (options.voice_clone_supported ? "true" : "false")
              << ", voice_profiles="
              << (options.voice_profiles_supported ? "true" : "false")
              << '\n';
    if (!options.reference_audio_path.empty()) {
        std::cout << "voice clone: reference_audio=" << options.reference_audio_path
                  << ", mode=" << (options.x_vector_only ? "x_vector_only" : "icl")
                  << '\n';
    }
}

bool has_sampling_overrides(const ProgramOptions& options) {
    return options.temperature.has_value() ||
           options.top_k.has_value() ||
           options.top_p.has_value() ||
           options.repetition_penalty.has_value() ||
           options.do_sample.has_value();
}

void require_sampling_overrides_supported(const ProgramOptions& options) {
    if (!options.sampling_overrides_supported) {
        throw std::runtime_error(
            "sampling overrides are disabled by the active worker profile; "
            "use the StyleExperiment launcher profile");
    }
}

void require_deterministic_seed_supported(const ProgramOptions& options) {
    if (!options.deterministic_seed_supported) {
        throw std::runtime_error(
            "the active worker profile does not guarantee deterministic explicit seeds");
    }
}

bool apply_interactive_command(ProgramOptions& options, const std::string& line) {
    const auto split = line.find(' ');
    const std::string command = line.substr(0, split);
    const std::string value = split == std::string::npos ? "" : line.substr(split + 1);

    if (command == "/voice") {
        if (value.empty()) {
            std::cerr << "usage: /voice <name>\n";
        }
        else if (options.voice_profiles_supported) {
            options.voice_id = value;
            options.speaker.clear();
            print_interactive_status(options);
        }
        else {
            options.speaker = value;
            options.voice_id.clear();
            print_interactive_status(options);
        }
        return true;
    }
    if (command == "/voices") {
        if (!options.voice_profiles_supported) {
            std::cout << "the active worker has no registered voice profiles\n";
        }
        else if (options.voice_ids.empty()) {
            std::cout << "the voice registry is empty\n";
        }
        else {
            std::cout << "registered voice profiles:\n";
            for (const std::string& voice_id : options.voice_ids) {
                std::cout << "  " << voice_id << '\n';
            }
        }
        return true;
    }
    if (command == "/language") {
        if (value.empty()) {
            std::cerr << "usage: /language <name>\n";
        }
        else {
            options.language = value;
            print_interactive_status(options);
        }
        return true;
    }
    if (command == "/style") {
        options.instruction = value;
        print_interactive_status(options);
        return true;
    }
    if (command == "/temperature") {
        if (value == "default") {
            options.temperature.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double temperature = parse_double(value, "/temperature");
            if (temperature <= 0.0 || temperature > 2.0) {
                throw std::runtime_error("/temperature must be in the interval (0, 2]");
            }
            options.temperature = temperature;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/top-k") {
        if (value == "default") {
            options.top_k.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const std::uint32_t top_k = parse_u32(value, "/top-k");
            if (top_k == 0) {
                throw std::runtime_error("/top-k must be greater than zero");
            }
            options.top_k = top_k;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/top-p") {
        if (value == "default") {
            options.top_p.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double top_p = parse_double(value, "/top-p");
            if (top_p <= 0.0 || top_p > 1.0) {
                throw std::runtime_error("/top-p must be in the interval (0, 1]");
            }
            options.top_p = top_p;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/repetition-penalty") {
        if (value == "default") {
            options.repetition_penalty.reset();
        }
        else {
            require_sampling_overrides_supported(options);
            const double repetition_penalty = parse_double(value, "/repetition-penalty");
            if (repetition_penalty < 1.0 || repetition_penalty > 2.0) {
                throw std::runtime_error("/repetition-penalty must be in the interval [1, 2]");
            }
            options.repetition_penalty = repetition_penalty;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/sample") {
        if (value == "on") {
            require_sampling_overrides_supported(options);
            options.do_sample = true;
        }
        else if (value == "off") {
            require_sampling_overrides_supported(options);
            options.do_sample = false;
        }
        else if (value == "default") {
            options.do_sample.reset();
        }
        else {
            std::cerr << "usage: /sample <on|off|default>\n";
            return true;
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/seed") {
        if (value == "default" || value == "off") {
            options.seed.reset();
        }
        else {
            require_deterministic_seed_supported(options);
            options.seed = parse_u64(value, "/seed");
        }
        print_interactive_status(options);
        return true;
    }
    if (command == "/sampling") {
        print_interactive_status(options);
        return true;
    }
    return false;
}

std::string utf8_from_wide(const std::wstring& value) {
    if (value.empty()) {
        return {};
    }

    const int byte_count = WideCharToMultiByte(
        CP_UTF8,
        WC_ERR_INVALID_CHARS,
        value.data(),
        static_cast<int>(value.size()),
        nullptr,
        0,
        nullptr,
        nullptr);
    if (byte_count <= 0) {
        throw std::runtime_error("failed to convert console input to UTF-8");
    }

    std::string utf8(static_cast<std::size_t>(byte_count), '\0');
    if (WideCharToMultiByte(
            CP_UTF8,
            WC_ERR_INVALID_CHARS,
            value.data(),
            static_cast<int>(value.size()),
            utf8.data(),
            byte_count,
            nullptr,
            nullptr) <= 0) {
        throw std::runtime_error("failed to convert console input to UTF-8");
    }
    return utf8;
}

bool read_interactive_line(std::string& line) {
    const HANDLE input = GetStdHandle(STD_INPUT_HANDLE);
    DWORD console_mode = 0;
    if (input == INVALID_HANDLE_VALUE ||
        input == nullptr ||
        !GetConsoleMode(input, &console_mode)) {
        return static_cast<bool>(std::getline(std::cin, line));
    }

    std::array<wchar_t, 4096> wide_buffer{};
    DWORD characters_read = 0;
    if (!ReadConsoleW(
            input,
            wide_buffer.data(),
            static_cast<DWORD>(wide_buffer.size() - 1),
            &characters_read,
            nullptr)) {
        return false;
    }

    std::wstring wide_line(wide_buffer.data(), characters_read);
    while (!wide_line.empty() &&
           (wide_line.back() == L'\r' || wide_line.back() == L'\n')) {
        wide_line.pop_back();
    }
    line = utf8_from_wide(wide_line);
    return true;
}

} // namespace

int wmain(int argc, wchar_t** argv) {
    try {
        ConsoleCodePageGuard console_code_page_guard;
        ProgramOptions options = parse_options(argc, argv);
        validate_options(options);
        if (options.help) {
            print_usage(std::cout, utf8_from_wide(argv[0]));
            return 0;
        }

        QwenTtsClientOptions client_options;
        client_options.session.startup_timeout = options.startup_timeout;

        QwenTtsClient client;
        if (!client.start(make_transport_options(options), client_options)) {
            throw std::runtime_error("failed to start Qwen TTS worker");
        }
        ReadyMessage ready;
        if (!client.ready_message(ready)) {
            client.stop();
            throw std::runtime_error("worker did not expose a ready payload");
        }
        options.sampling_overrides_supported = ready.capabilities.sampling_overrides;
        options.deterministic_seed_supported = ready.capabilities.deterministic_seed;
        options.voice_clone_supported = ready.capabilities.voice_clone;
        options.voice_profiles_supported = ready.capabilities.voice_profiles;
        options.voice_ids = ready.voice_ids;
        if (!options.reference_audio_path.empty() && !options.voice_clone_supported) {
            client.stop();
            throw std::runtime_error(
                "the active worker does not advertise voice clone support; "
                "launch a Qwen Base model with --reference-audio");
        }
        if (!options.voice_id.empty() && !options.voice_profiles_supported) {
            client.stop();
            throw std::runtime_error(
                "the active worker has no registered voice-profile registry; "
                "launch it with --voice-registry-path");
        }
        if (has_sampling_overrides(options) && !options.sampling_overrides_supported) {
            client.stop();
            throw std::runtime_error(
                "sampling overrides are disabled by the active worker profile; "
                "use the StyleExperiment launcher profile");
        }
        if (options.seed.has_value() && !options.deterministic_seed_supported) {
            client.stop();
            throw std::runtime_error(
                "the active worker profile does not guarantee deterministic explicit seeds");
        }

        std::unique_ptr<EtwPlaybackMarkers> etw_playback_markers;
        if (options.etw_playback_markers) {
            etw_playback_markers = std::make_unique<EtwPlaybackMarkers>();
        }
        std::unique_ptr<PlaybackMetrics> playback_metrics;
        if (!options.playback_metrics_file.empty()) {
            playback_metrics = std::make_unique<PlaybackMetrics>(etw_playback_markers.get());
        }
        WaveOutPlayer player(playback_metrics.get());
        ActiveRequestState active_state;

        if (!options.text.empty()) {
            OneShotState state;
            if (playback_metrics != nullptr) {
                playback_metrics->begin_request();
            }
            submit_request(client, player, active_state, options, options.text, &state);
            if (!wait_for_one_shot(state, std::chrono::minutes(5))) {
                cancel_active_request(client, player, active_state);
                client.stop();
                throw std::runtime_error("one-shot synthesis timed out");
            }
            if (!state.success) {
                client.stop();
                throw std::runtime_error(state.message.empty() ? "one-shot synthesis failed" : state.message);
            }
            player.wait_until_idle(std::chrono::minutes(5));
            if (playback_metrics != nullptr) {
                playback_metrics->mark_playback_completed();
                playback_metrics->write_json_file(options.playback_metrics_file);
            }
            client.stop();
            return 0;
        }

        print_usage(std::cout, utf8_from_wide(argv[0]));
        print_interactive_status(options);
        for (std::string line; std::cout << "> " && read_interactive_line(line);) {
            if (line.empty()) {
                continue;
            }
            if (line == "/quit" || line == "/exit") {
                break;
            }
            if (line == "/help") {
                print_usage(std::cout, utf8_from_wide(argv[0]));
                continue;
            }
            if (line == "/cancel") {
                cancel_active_request(client, player, active_state);
                std::cout << "cancelled active request\n";
                continue;
            }
            if (line.front() == '/') {
                try {
                    if (!apply_interactive_command(options, line)) {
                        std::cerr << "unknown command; use /help\n";
                    }
                }
                catch (const std::exception& exc) {
                    std::cerr << "command error: " << exc.what() << '\n';
                }
                continue;
            }
            submit_request(client, player, active_state, options, line);
        }

        cancel_active_request(client, player, active_state);
        client.stop();
        return 0;
    }
    catch (const std::exception& exc) {
        std::cerr << "qwen_tts_play: " << exc.what() << '\n';
        std::cerr << "Run with --help for usage.\n";
        return 1;
    }
}
