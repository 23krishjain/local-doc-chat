# Day 1: local image question client

## Built
A small standard-library HTTP client and command line entry point. One image
and question go to local Ollama; the answer comes back without streaming.
Model choice and timeout are explicit. Network failures, bad responses and
missing/oversized/non-image files produce useful errors without logging images.

## Decisions
- Start with the actual Ollama HTTP contract rather than adding an orchestration
  framework before there is a retrieval pipeline.
- Restrict destinations to loopback, disable proxies and redirects. Private
  images should not accidentally leave the machine through configuration.
- Do not download model weights automatically or silently fall back to a
  differently licensed model. Qwen's 3B and 7B variants have different licenses.
- No tools run from model output. An image is evidence, not an instruction.

## Checks and limits
Eleven HTTP fixture/error tests pass. They test wiring, not AI understanding.
A synthetic receipt is supplied with an expected total of INR 180. A real
vision-model run has NOT been completed. Hardware fit, speed, answer accuracy
and resilience to misleading image instructions are unverified. The day is
partial on the model-setup goal, even though client code is ready to try.

## Interview practice
1. Why use base64 in the request, and what is its size overhead?
2. What do HTTP fixture tests prove, and what can they never prove about an LLM?
3. Why is a 6GB model download not a promise it fits a 6GB GPU?
4. Why must model licensing be checked per variant?
5. Why are redirects and proxies relevant when the app is meant to stay local?
