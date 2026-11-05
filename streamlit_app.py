import io
import os
import re
import tempfile
import time

import streamlit as st
from docx import Document
from google import genai
from google.genai import types

MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]

st.set_page_config(page_title="Lecture Notes", page_icon="📝")
st.title("📝 Lecture Notes")
st.write("Step 1: get the exact words of the lecture. Step 2: turn them into notes.")


@st.cache_resource
def get_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


def call_gemini(contents):
    client = get_client()
    last_error = None
    for wait in (0, 5, 10):
        if wait:
            time.sleep(wait)
        for model in MODELS:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(temperature=0),
                )
                return response.text
            except Exception as e:
                last_error = e
                if "503" not in str(e) and "UNAVAILABLE" not in str(e):
                    raise
    raise last_error


def transcribe(audio_file, topic):
    suffix = os.path.splitext(audio_file.name)[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(audio_file.getvalue())
        path = tmp.name
    try:
        uploaded = get_client().files.upload(file=path)
        prompt = f"""Transcribe this audio word for word, exactly as spoken.
Do not summarize, shorten, paraphrase, reorder, or fix the speaker's grammar.
Do not skip anything and do not add headings, bullet points, or commentary.
Output only the spoken words, in plain paragraphs.
If a word is unclear, write [unclear] instead of guessing.
Topic (use it only to spell technical terms and names correctly): {topic}"""
        return call_gemini([prompt, uploaded])
    finally:
        os.remove(path)


def make_notes(transcript, topic):
    prompt = f"""You are a student note-taker. Turn this lecture transcript into clear study notes.
Course/topic: {topic}

Use headings, bullet points, key terms with short definitions, and a short summary at the end.
Only use what is in the transcript. If something is unclear, say so instead of guessing.

Transcript:
{transcript}"""
    return call_gemini([prompt])


def build_docx(title, text, formatted):
    doc = Document()
    doc.add_heading(title, 0)
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if not formatted:
            doc.add_paragraph(line)
            continue
        clean = line.replace("**", "")
        if line.startswith("### "):
            doc.add_heading(clean[4:], 3)
        elif line.startswith("## "):
            doc.add_heading(clean[3:], 2)
        elif line.startswith("# "):
            doc.add_heading(clean[2:], 1)
        elif line.startswith(("* ", "- ")):
            doc.add_paragraph(clean[2:], style="List Bullet")
        else:
            doc.add_paragraph(clean)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

uploaded_audio = st.file_uploader(
    "Upload lecture audio", type=["mp3", "wav", "m4a", "aac", "ogg"]
)
topic = st.text_input("Course / topic (helps spell terms correctly)")
title = st.text_input("Title for your files", value="Lecture Notes")
safe = re.sub(r"[^\w\- ]", "", title).strip() or "lecture"

if st.button("1. Transcribe", type="primary"):
    if uploaded_audio is None:
        st.warning("Please upload an audio file first.")
    else:
        with st.spinner("Listening... this can take a few minutes."):
            try:
                st.session_state["transcript"] = transcribe(uploaded_audio, topic)
                st.session_state.pop("notes", None)
            except Exception as e:
                st.session_state.pop("transcript", None)
                st.error(f"Something went wrong: {e}")

if "transcript" in st.session_state:
    st.subheader("Transcript")
    st.caption("Check this against the audio. You can fix mistakes before making notes.")
    st.text_area("Transcript", key="transcript", height=300, label_visibility="collapsed")
    st.download_button(
        "Download transcript (Word)",
        data=build_docx(title, st.session_state["transcript"], formatted=False),
        file_name=f"{safe} - transcript.docx",
        mime=DOCX_MIME,
    )

    if st.button("2. Make notes from transcript", type="primary"):
        with st.spinner("Writing notes..."):
            try:
                st.session_state["notes"] = make_notes(
                    st.session_state["transcript"], topic
                )
            except Exception as e:
                st.session_state.pop("notes", None)
                st.error(f"Something went wrong: {e}")

if "notes" in st.session_state:
    st.subheader("Notes")
    st.markdown(st.session_state["notes"])
    st.download_button(
        "Download notes (Word)",
        data=build_docx(title, st.session_state["notes"], formatted=True),
        file_name=f"{safe} - notes.docx",
        mime=DOCX_MIME,
    )
