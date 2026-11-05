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
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

st.set_page_config(page_title="Lecture Notes", page_icon="📝")
st.title("📝 Lecture Notes")
st.write("Step 1: get the exact words of the lecture. Step 2: turn them into notes. Step 3: learn the topic.")


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


def teach(transcript, topic):
    prompt = f"""A first-year university student just attended a lecture on: {topic or "the topic below"}.
Use the transcript only to see what the lecturer covered. Then teach the topic more broadly, in simple clear English.

Structure your answer like this:
## What the lecturer covered
One or two sentences.
## The topic explained simply
A beginner-friendly explanation of the main ideas.
## Extra background (not in the lecture)
Useful context the lecturer did not mention. Label this clearly.
## Examples
Two or three clear examples.
## Common mistakes
What students often get wrong.
## Practice questions
Three questions, each with a short answer.

Rules: do not invent facts, statistics, quotes, or sources. If you are not sure about something, say so. Do not claim the lecturer said anything that is not in the transcript.

Transcript:
{transcript}"""
    return call_gemini([prompt])


def add_formatted(doc, text):
    # Headings from the AI text sit one level below the section heading.
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        clean = line.replace("**", "")
        m = re.match(r"^(#{1,4})\s+(.*)", clean)
        if m:
            level = min(len(m.group(1)) + 1, 4)
            doc.add_heading(m.group(2), level)
        elif line.startswith(("* ", "- ")):
            doc.add_paragraph(clean[2:], style="List Bullet")
        else:
            doc.add_paragraph(clean)


def build_full_docx(title, transcript, notes, lesson):
    doc = Document()
    doc.add_heading(title, 0)
    first = True

    if transcript:
        doc.add_heading("Transcript", 1)
        p = doc.add_paragraph()
        p.add_run("The exact words of the lecture, as transcribed by AI. Check it against the audio.").italic = True
        for line in transcript.split("\n"):
            if line.strip():
                doc.add_paragraph(line.strip())
        first = False

    if notes:
        if not first:
            doc.add_page_break()
        doc.add_heading("Study Notes", 1)
        p = doc.add_paragraph()
        p.add_run("Based only on the transcript above.").italic = True
        add_formatted(doc, notes)
        first = False

    if lesson:
        if not first:
            doc.add_page_break()
        doc.add_heading("Lesson", 1)
        p = doc.add_paragraph()
        p.add_run("Written by AI, not the lecturer. It can make mistakes, so check important facts in your textbook or with your lecturer.").italic = True
        add_formatted(doc, lesson)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


uploaded_audio = st.file_uploader(
    "Upload lecture audio", type=["mp3", "wav", "m4a", "aac", "ogg"]
)
topic = st.text_input("Course / topic (helps spell terms correctly)")
title = st.text_input("Title for your document", value="Lecture Notes")
safe = re.sub(r"[^\w\- ]", "", title).strip() or "lecture"

if st.button("1. Transcribe", type="primary"):
    if uploaded_audio is None:
        st.warning("Please upload an audio file first.")
    else:
        with st.spinner("Listening... this can take a few minutes."):
            try:
                st.session_state["transcript"] = transcribe(uploaded_audio, topic)
                st.session_state.pop("notes", None)
                st.session_state.pop("lesson", None)
            except Exception as e:
                st.session_state.pop("transcript", None)
                st.error(f"Something went wrong: {e}")

if "transcript" in st.session_state:
    st.subheader("Transcript")
    st.caption("Check this against the audio. You can fix mistakes before making notes.")
    st.text_area("Transcript", key="transcript", height=300, label_visibility="collapsed")

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

if "transcript" in st.session_state:
    st.divider()
    st.caption("Optional: learn the topic beyond what the lecturer said.")
    if st.button("3. Teach me this topic"):
        with st.spinner("Preparing your lesson..."):
            try:
                st.session_state["lesson"] = teach(
                    st.session_state["transcript"], topic
                )
            except Exception as e:
                st.session_state.pop("lesson", None)
                st.error(f"Something went wrong: {e}")

if "lesson" in st.session_state:
    st.subheader("Lesson (written by AI, not the lecturer)")
    st.warning("AI can make mistakes. Check important facts in your textbook or with your lecturer.")
    st.markdown(st.session_state["lesson"])

if "transcript" in st.session_state:
    st.divider()
    st.download_button(
        "⬇️ Download everything (one Word file)",
        data=build_full_docx(
            title,
            st.session_state.get("transcript"),
            st.session_state.get("notes"),
            st.session_state.get("lesson"),
        ),
        file_name=f"{safe}.docx",
        mime=DOCX_MIME,
        type="primary",
    )
    st.caption("The file includes whatever you have made so far: transcript, notes, and lesson.")
