#!/usr/bin/env python3
"""Local instruction-driven generative image editor for pSquare.

Runs only on compute-01. Uses InstructPix2Pix with CUDA when available and CPU
offload to stay within the Quadro RTX 3000 6GB VRAM envelope. Inputs, outputs,
and prompt files are controller-generated paths; prompt text is never executed
as shell code.
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("HF_HOME", "/home/p2ops/.local/share/psquare-generative/hf")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from PIL import Image, ImageOps
import torch
from diffusers import EulerAncestralDiscreteScheduler, StableDiffusionInstructPix2PixPipeline

MODEL = "timbrooks/instruct-pix2pix"
MAX_SIDE = 768
MIN_SIDE = 256


def fit_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    w, h = image.size
    scale = min(1.0, MAX_SIDE / max(w, h))
    nw = max(MIN_SIDE, int(round(w * scale / 8.0)) * 8)
    nh = max(MIN_SIDE, int(round(h * scale / 8.0)) * 8)
    if (nw, nh) != (w, h):
        image = image.resize((nw, nh), Image.Resampling.LANCZOS)
    return image


def load_pipeline() -> StableDiffusionInstructPix2PixPipeline:
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    pipe = StableDiffusionInstructPix2PixPipeline.from_pretrained(
        MODEL,
        torch_dtype=dtype,
        use_safetensors=True,
    )
    pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
    pipe.set_progress_bar_config(disable=True)
    pipe.enable_attention_slicing("max")
    if torch.cuda.is_available():
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cpu")
    return pipe


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: psquare_generative.py INPUT OUTPUT PROMPT_FILE", file=sys.stderr)
        return 2

    src = pathlib.Path(sys.argv[1])
    dst = pathlib.Path(sys.argv[2])
    prompt_file = pathlib.Path(sys.argv[3])
    if not src.is_file() or not prompt_file.is_file():
        print("missing input or prompt file", file=sys.stderr)
        return 3

    instruction = prompt_file.read_text(encoding="utf-8", errors="replace").strip()
    if not instruction or len(instruction) > 700:
        print("invalid instruction length", file=sys.stderr)
        return 4

    image = fit_image(Image.open(src))
    pipe = load_pipeline()
    generator = torch.Generator(device="cpu").manual_seed(42)
    result = pipe(
        instruction,
        image=image,
        num_inference_steps=20,
        guidance_scale=7.5,
        image_guidance_scale=1.5,
        generator=generator,
    ).images[0]

    dst.parent.mkdir(parents=True, exist_ok=True)
    result.save(dst, format="PNG", optimize=True)
    print(f"GENERATIVE_EDIT=ready size={result.width}x{result.height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
