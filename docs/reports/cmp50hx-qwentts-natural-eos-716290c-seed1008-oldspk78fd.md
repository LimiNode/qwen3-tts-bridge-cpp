# Historical `.spk` EOS replay — seed 1008

The earlier multiseed evidence used speaker latent SHA-256 `78FD1104…`, while the newer matrix used `18748F08…`; the RVQ fixture was identical. This replay uses the historical `.spk` with qwentts.cpp `716290c`, seed `1008`, normal production sampling, no forced history, no EOS disabling, and a 256-frame limit.

It terminates naturally at frame 121 (`9.68 s`, TTFA `1927.0 ms`, total `6826.7 ms`, RTF `0.705`). This closes the conditioning provenance gap without claiming that the two `.spk` fixtures are interchangeable.
