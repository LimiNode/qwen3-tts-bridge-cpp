# Local Voice Clone

Base Qwen3-TTS models can synthesize speech from a local reference WAV. This
is separate from the `0.6B-CustomVoice` preset-speaker model used by the normal
playback CLI. The bridge keeps the reference path and its transcript separate
from spoken text, sends both over stdio, and never copies the audio into Git.

The local `kraftwerk_robot_3_ru.wav` reference is 4.344 seconds long and has
been smoke-tested through the C++ CLI with the cached `1.7B-Base` model. A few
seconds of clear reference speech can be enough, but quality remains sensitive
to recording quality, transcript accuracy, and the target text.

For the local robot example, use the existing recording as a reference and its
actual transcript:

```powershell
.\scripts\start-qwen-tts-clone-play.ps1 `
  -ReferenceAudioPath 'C:\_repoz\tmp\kraftwerk_robot_3_ru.wav' `
  -ReferenceText 'Я твой слуга, я твой работник' `
  -Text 'Я твой робот. Я твой работник. Выполняю приказ немедленно.'
```

The script uses the locally cached `Qwen/Qwen3-TTS-12Hz-1.7B-Base` model when
available. Pass `-ModelPath` to select another local snapshot or Hugging Face
model ID.

The default is ICL cloning: `ReferenceText` must match the reference recording
as closely as possible. `-XVectorOnly` is an explicit fallback that extracts a
speaker embedding without the transcript; it is less constrained by reference
content and can sound less faithful.

The project does not distribute third-party recordings or present generated
audio as an authentic source recording. Use only references you are permitted
to process, label generated output as synthesized, and do not use this example
to impersonate a real person.
