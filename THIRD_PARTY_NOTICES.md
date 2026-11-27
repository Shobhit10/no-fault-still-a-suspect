# Third-party notices

No third-party package, binary or data file is vendored in this repository. Python packages are
installed with pip (`requirements.txt`, `requirements-rcaeval.txt`); the live harness pulls public
container images (`curlimages/curl`, `nicolaka/netshoot`) and, for distroless containers only, a
static busybox binary at run time.

## RCAEval (code excerpt and benchmark data)

* `fouroutcome/rankers.py`: `drop_time`, `drop_constant`, `convert_mem_mb`, `preprocess` and the
  column scoring in `column_scores` follow RCAEval's `RCAEval/io/time_series.py` and the `baro` and
  `nsigma` entry points of `RCAEval/e2e` (about 40 lines, re-implemented so that BARO and n-sigma
  run without the RCAEval package; the paper's runs called RCAEval itself and checked that this
  computation returns the identical ranking).
* `fouroutcome/rcaeval_adapter.py` unwraps RCAEval's exception-handling decorator in the same way
  as RCAEval's `rca` wrapper is written (a few lines).
* `data/e2/` and `data/rq1/` contain the authors' per-call results on the RCAEval benchmark
  (Hugging Face dataset `phamquiluan/RCAEval`, revision `afeacb11`), which name RCAEval cases and
  metric columns. The benchmark telemetry is not redistributed. The dataset card states the MIT
  licence; the code repository states: "For the code implemented by us and for our datasets, we
  distribute them under the MIT LICENSE."

RCAEval licence:

```
MIT License

Copyright (c) 2024 Luan Pham

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Benchmark applications

The live experiments ran the open-source applications Online Boutique, Sock Shop, OpenTelemetry
Demo, DeathStarBench (hotel reservation) and Train Ticket, deployed from their public releases. No
part of them is included here; `experiments/live/config.example.json` and
`experiments/live/probe/health_probe.yaml` name their services and public endpoints.
