#include "examples/common/cli_parsing.hpp"

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#define CHECK(expr)                                                            \
    do {                                                                       \
        if (!(expr)) {                                                         \
            std::cerr << "CHECK failed: " #expr << " at " << __FILE__ << ':'  \
                      << __LINE__ << '\n';                                     \
            return EXIT_FAILURE;                                               \
        }                                                                      \
    } while (false)

namespace {

using qwen_tts_examples::cli::parse_double;
using qwen_tts_examples::cli::parse_int;
using qwen_tts_examples::cli::parse_u32;
using qwen_tts_examples::cli::parse_u64;

template <typename Function>
bool rejects(Function&& function, const std::string& expected_message) {
    try {
        static_cast<void>(function());
    }
    catch (const std::runtime_error& error) {
        return error.what() == expected_message;
    }
    return false;
}

} // namespace

int main() {
    using qwen_tts_examples::cli::require_value;

    {
        std::vector<std::string> arguments{
            "example",
            "--text=Привет",
            "--language",
            "ru",
        };
        for (int index = 1; index < static_cast<int>(arguments.size()); ++index) {
            const std::string current = arguments[index];
            const auto argument_at = [&](int argument_index) {
                return arguments[static_cast<std::size_t>(argument_index)];
            };
            if (current.rfind("--text", 0) == 0) {
                CHECK(require_value(
                          index,
                          static_cast<int>(arguments.size()),
                          current,
                          argument_at,
                          "--text") == "Привет");
            }
            else if (current == "--language") {
                CHECK(require_value(
                          index,
                          static_cast<int>(arguments.size()),
                          current,
                          argument_at,
                          "--language") == "ru");
            }
        }
    }

    {
        int index = 1;
        const std::vector<std::string> arguments{"example", "--text"};
        const auto argument_at = [&](int argument_index) {
            return arguments[static_cast<std::size_t>(argument_index)];
        };
        CHECK(rejects(
            [&] {
                return require_value(
                    index,
                    static_cast<int>(arguments.size()),
                    arguments[index],
                    argument_at,
                    "--text");
            },
            "missing value for --text"));
    }

    CHECK(parse_u32("0", "--value") == 0);
    CHECK(parse_u32("+1", "--value") == 1);
    CHECK(parse_u32(" 1", "--value") == 1);
    CHECK(parse_u32("4294967295", "--value") ==
          (std::numeric_limits<std::uint32_t>::max)());
    CHECK(rejects(
        [] { return parse_u32("-1", "--value"); },
        "invalid integer for --value: -1"));
    CHECK(rejects(
        [] { return parse_u32("  -1", "--value"); },
        "invalid integer for --value:   -1"));
    CHECK(rejects(
        [] { return parse_u32("4294967296", "--value"); },
        "invalid integer for --value: 4294967296"));
    CHECK(rejects(
        [] { return parse_u32("12x", "--value"); },
        "invalid integer for --value: 12x"));
    CHECK(rejects(
        [] { return parse_u32("1 ", "--value"); },
        "invalid integer for --value: 1 "));
    CHECK(rejects(
        [] { return parse_u32("999999999999999999999999999999999999999999", "--value"); },
        "invalid integer for --value: 999999999999999999999999999999999999999999"));

    CHECK(parse_u64("0", "--seed") == 0);
    CHECK(parse_u64("+1", "--seed") == 1);
    CHECK(parse_u64("18446744073709551615", "--seed") ==
          (std::numeric_limits<std::uint64_t>::max)());
    CHECK(rejects(
        [] { return parse_u64("-1", "--seed"); },
        "invalid integer for --seed: -1"));
    CHECK(rejects(
        [] { return parse_u64("18446744073709551616", "--seed"); },
        "invalid integer for --seed: 18446744073709551616"));

    CHECK(parse_int("-1", "--count") == -1);
    CHECK(parse_int("+1", "--count") == 1);
    CHECK(parse_int("-2147483648", "--count") ==
          (std::numeric_limits<int>::min)());
    CHECK(parse_int("2147483647", "--count") ==
          (std::numeric_limits<int>::max)());
    CHECK(rejects(
        [] { return parse_int("2147483648", "--count"); },
        "invalid integer for --count: 2147483648"));
    CHECK(rejects(
        [] { return parse_int("-2147483649", "--count"); },
        "invalid integer for --count: -2147483649"));

    CHECK(parse_double("0", "--temperature") == 0.0);
    CHECK(parse_double("+1.25", "--temperature") == 1.25);
    CHECK(parse_double(" 1.25", "--temperature") == 1.25);
    CHECK(rejects(
        [] { return parse_double("nan", "--temperature"); },
        "invalid number for --temperature: nan"));
    CHECK(rejects(
        [] { return parse_double("inf", "--temperature"); },
        "invalid number for --temperature: inf"));
    CHECK(rejects(
        [] { return parse_double("1.0x", "--temperature"); },
        "invalid number for --temperature: 1.0x"));
    const std::string huge_decimal(400, '9');
    CHECK(rejects(
        [&] { return parse_double(huge_decimal, "--temperature"); },
        "invalid number for --temperature: " + huge_decimal));

    return EXIT_SUCCESS;
}
