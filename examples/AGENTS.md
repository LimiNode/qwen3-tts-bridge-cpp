# `examples/` — executable examples

Examples are integration probes, not a second library layer. Keep transport,
protocol, and worker policy in the library; examples may compose them and own
console/playback concerns.

Interactive commands must report the active profile, language, voice, and
sampling policy. Any automatic profile choice must happen at a request
boundary and print the selected route. Do not hide a fallback, quality tradeoff,
or 30-second safety limit in an example.
