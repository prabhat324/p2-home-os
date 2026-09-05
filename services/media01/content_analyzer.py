#!/usr/bin/env python3
"""Create transcript, captions, edit notes, and speech-duplication evidence."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def stamp():
    return datetime.now(timezone.utc).isoformat()


def srt_time(seconds):
    ms = max(0, round(float(seconds) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def words_of(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def caption_chunks(segment, maximum=14):
    words = segment.get("words", [])
    if not words:
        return [{"start":segment["start"],"end":segment["end"],"text":segment["text"]}]
    chunks=[]
    for i in range(0,len(words),maximum):
        part=words[i:i+maximum]
        chunks.append({"start":part[0]["start"],"end":part[-1]["end"],"text":" ".join(w["word"].strip() for w in part)})
    return chunks


def repeated_speech(segments, window=12, minimum_gap=12):
    timeline = []
    for segment in segments:
        tokens = words_of(segment["text"])
        duration = max(segment["end"] - segment["start"], 0.01)
        for i, token in enumerate(tokens):
            timeline.append((token, segment["start"] + duration * i / max(len(tokens), 1)))
    seen, repeats = {}, []
    for index in range(max(0, len(timeline) - window + 1)):
        phrase = tuple(token for token, _ in timeline[index:index + window])
        when = timeline[index][1]
        previous = seen.get(phrase)
        if previous is not None and when - previous >= minimum_gap:
            repeats.append({"first_second": round(previous, 2), "repeat_second": round(when, 2),
                            "words": window, "phrase": " ".join(phrase)})
        else:
            seen[phrase] = when
    # Suppress overlapping reports from one duplicated passage.
    compact = []
    for item in repeats:
        if not compact or item["repeat_second"] - compact[-1]["repeat_second"] > 3:
            compact.append(item)
    return compact[:50]


def claim_flags(segments):
    pattern = re.compile(r"(?:\$\s?\d|\b\d+(?:[,.]\d+)*(?:\s?%|\s?(?:million|billion|thousand))?\b|\b(?:19|20)\d{2}\b)", re.I)
    flags = []
    for segment in segments:
        found = pattern.findall(segment["text"])
        if found:
            flags.append({"second": round(segment["start"], 2), "text": segment["text"].strip(),
                          "reason": "number/date/currency requires source verification"})
    return flags


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--language", default="en")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    from faster_whisper import WhisperModel
    engine = {"device": "cuda", "compute_type": "float16"}
    try:
        model = WhisperModel(args.model, device=engine["device"], compute_type=engine["compute_type"])
    except Exception as gpu_error:
        engine = {"device": "cpu", "compute_type": "int8", "gpu_error": str(gpu_error)}
        model = WhisperModel(args.model, device=engine["device"], compute_type=engine["compute_type"])

    def transcribe(current_model):
        stream, current_info = current_model.transcribe(
            str(args.video), language=args.language, beam_size=5, vad_filter=True,
            condition_on_previous_text=True, word_timestamps=True
        )
        # Materialize the lazy stream here so CUDA execution errors are caught.
        current_segments = [
            {"start": float(s.start), "end": float(s.end), "text": s.text.strip(), "words": [{"start":float(w.start),"end":float(w.end),"word":w.word,"probability":float(w.probability)} for w in (s.words or [])]}
            for s in stream if s.text.strip()
        ]
        return current_segments, current_info

    try:
        segments, info = transcribe(model)
    except Exception as gpu_runtime_error:
        if engine["device"] != "cuda":
            raise
        engine = {"device": "cpu", "compute_type": "int8",
                  "gpu_runtime_error": str(gpu_runtime_error)}
        model = WhisperModel(args.model, device="cpu", compute_type="int8")
        segments, info = transcribe(model)
    transcript_text = "\n".join(f"[{srt_time(s['start'])[:-4]}] {s['text']}" for s in segments) + "\n"
    (args.output_dir / "transcript.txt").write_text(transcript_text)
    (args.output_dir / "transcript.json").write_text(json.dumps({
        "created_at": stamp(), "model": args.model, "engine": engine,
        "language": info.language, "language_probability": info.language_probability,
        "segments": segments,
    }, indent=2))

    captions = [chunk for segment in segments for chunk in caption_chunks(segment)]
    srt = []
    for number, cue in enumerate(captions, 1):
        # Fourteen words max: two restrained lines of up to seven words.
        cue_words = cue["text"].split()
        text = " ".join(cue_words[:7])
        if len(cue_words) > 7:
            text += "\n" + " ".join(cue_words[7:14])
        srt.extend([str(number), f"{srt_time(cue['start'])} --> {srt_time(cue['end'])}", text, ""])
    (args.output_dir / "captions.srt").write_text("\n".join(srt))

    duplicates = repeated_speech(segments)
    claims = claim_flags(segments)
    report = {
        "created_at": stamp(), "status": "FAIL" if duplicates else "PASS",
        "probable_repeated_spoken_sections": duplicates,
        "fact_check_flags": claims,
        "protected_terms_to_verify": ["Wasaga Beach", "BeSquare by pSquare"],
        "editorial_notes": [
            "Refresh talking-head visuals with relevant B-roll or primary documents every 20–30 seconds.",
            "Return to the presenter between chapters.",
            "Use only sourced, labeled data in graphs; decorative line graphics are prohibited.",
            "Verify every flagged number, date, quotation, name, and current claim against primary sources.",
            "Keep political treatment neutral; candidate interviews must remain essentially complete.",
        ],
    }
    (args.output_dir / "content-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"status": report["status"], "segments": len(segments),
                      "duplicates": len(duplicates), "fact_check_flags": len(claims),
                      "output_dir": str(args.output_dir)}, indent=2))
    return 0  # Findings are review evidence, not an execution failure.


if __name__ == "__main__":
    raise SystemExit(main())

