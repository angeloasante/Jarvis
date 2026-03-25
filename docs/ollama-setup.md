# Setting Up Ollama (Local LLM)

Ollama runs LLMs locally on your Mac. FRIDAY uses it as the local inference backend — and as automatic fallback when cloud (Groq) is unavailable.

## Install Ollama

```bash
# Download from https://ollama.com or use Homebrew:
brew install ollama
```

This installs the `ollama` CLI and the Ollama app. On first launch, it sets up the local server at `http://localhost:11434`.

## Pull the Model

```bash
# Pull the model FRIDAY uses (Qwen 3.5 9B, ~6GB download)
ollama pull qwen3.5:9b
```

This downloads the quantized model to `~/.ollama/models/`. It only downloads once — subsequent runs use the cached model.

## Start the Server

```bash
# Option 1: Launch the Ollama app (from Applications or Spotlight)
# The app runs the server in the background with a menu bar icon.

# Option 2: Start from terminal
ollama serve
```

The server must be running for FRIDAY to use local inference. If you're using cloud (Groq), the server is only needed as a fallback.

## Verify It Works

```bash
# Quick test — should respond in a few seconds
ollama run qwen3.5:9b "hello"

# Check the server is running
curl http://localhost:11434/api/tags
```

## Hardware Requirements

| Mac | RAM | Performance |
|-----|-----|------------|
| M1/M2/M3/M4 (any) | 16GB+ | Works well, 10-25s per call |
| M1/M2/M3/M4 Pro/Max | 32GB+ | Faster, can run larger models |
| Intel Mac | 16GB+ | Works but slower (CPU only) |

The model uses ~6GB of RAM. Ollama keeps it loaded in memory (`keep_alive: -1`) so subsequent calls are faster — no reload time.

## Troubleshooting

- **"connection refused"** — Ollama server isn't running. Launch the app or run `ollama serve`.
- **"model not found"** — Run `ollama pull qwen3.5:9b` to download it.
- **Slow responses** — Normal on fanless Macs (M4 Air). GPU throttles under sustained load. Use cloud (Groq) for speed.
- **Out of memory** — Close other heavy apps. The 9B model needs ~6GB free RAM.
