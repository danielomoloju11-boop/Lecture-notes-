import io
import os
import re
import tempfile
import time

import streamlit as st
from docx import Document
from google import genai
from google.genai import types
from PIL import Image, ImageOps

MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

st.set_page_config(page_title="Lecture Notes", page_icon="📝")
st.title("📝 Lecture Notes")
st.write("Upload the lecture audio and, if you like, photos of the board or slides.")


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


def prep_image(file):
    img = Image.open(file)
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def read_board(image_files, topic):
    prompt = f"""These are photos of a lecture board or slides. Topic: {topic}
Copy exactly what is written or drawn, in the order a student would read it.
Write equations in plain text that works in a Word file (for example: x^2 + 3x - 4 = 0, sqrt(x), (a+b)/(c+d)).
For a diagram, describe it briefly in square brackets, for example [diagram: a ball thrown at an angle, with its path drawn as a curve].
Do not solve, explain, or correct anything. If something is hard to read, write [unclear] instead of guessing.
Start each photo with a line like "Photo 1:"."""
    parts = [prompt]
    for f in image_files:
        parts.append(types.Part.from_bytes(data=prep_image(f), mime_type="image/jpeg"))
    return call_gemini(parts)


def source_material(transcript, board):
    text = f"Transcript of what the lecturer said:\n{transcript}"
    if board and board.strip():
        text += f"\n\nWhat was written on the board or slides:\n{board}"
    return text


def make_notes(transcript, board, topic):
    prompt = f"""You are a student note-taker. Turn this lecture material into clear study notes.
Course/topic: {topic}

Use headings, bullet points, key terms with short definitions, and a short summary at the end.
Include the equations and diagrams from the board where they belong. Write equations in plain text.
Only use what is in the material below. If something is unclear, say so instead of guessing.

{source_material(transcript, board)}"""
    return call_gemini([prompt])


def teach(transcript, board, topic):
    prompt = f"""A first-year university student just attended a lecture on: {topic or "the topic below"}.
Use the material below only to see what the lecturer covered. Then teach the topic more broadly, in simple clear English.
Write equations in plain text that works in a Word file.

Structure your answer like this:
## What the lecturer covered
One or two sentences.
## The topic explained simply
A beginner-friendly explanation of the main ideas.
## Extra background (not in the lecture)
Useful context the lecturer did not mention. Label this clearly.
## Examples
Two or three clear examples. For maths or physics, show each step.
## Common mistakes
What students often get wrong.
## Practice questions
Three questions, each with a short answer.

Rules: do not invent facts, statistics, quotes, or sources. If you are not sure about something, say so. Do not claim the lecturer said anything that is not in the material.

{source_material(transcript, board)}"""
    return call_gemini([prompt])


def add_formatted(doc, text):
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


def add_plain(doc, text):
    for line in text.split("\n"):
        if line.strip():
            doc.add_paragraph(line.strip())


def build_full_docx(title, transcript, board, notes, lesson):
    doc = Document()
    doc.add_heading(title, 0)
    first = True

    def section(heading, note):
        nonlocal first
        if not first:
            doc.add_page_break()
        first = False
        doc.add_heading(heading, 1)
        doc.add_paragraph().add_run(note).italic = True

    if transcript:
        section("Transcript", "The exact words of the lecture, as transcribed by AI. Check it against the audio.")
        add_plain(doc, transcript)
    if board and board.strip():
        section("Board and Slides", "Copied from your photos by AI. Check it against the originals.")
        add_plain(doc, board)
    if notes:
        section("Study Notes", "Based only on the transcript and board content above.")
        add_formatted(doc, notes)
    if lesson:
        section("Lesson", "Written by AI, not the lecturer. It can make mistakes, so check important facts and worked examples in your textbook or with your lecturer.")
        add_formatted(doc, lesson)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


uploaded_audio = st.file_uploader(
    "Upload lecture audio", type=["mp3", "wav", "m4a", "aac", "ogg"]
)
board_photos = st.file_uploader(
    "Photos of the board or slides (optional)",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
)
topic = st.text_input("Course / topic (helps spell terms correctly)")
title = st.text_input("Title for your document", value="Lecture Notes")
safe = re.sub(r"[^\w\- ]", "", title).strip() or "lecture"

if st.button("1. Transcribe audio", type="primary"):
    if uploaded_audio is None:
        st.warning("Please upload an audio file first.")
    else:
        with st.spinner("Listening... this can take a few minutes."):
            try:
                st.session_state["transcript"] = transcribe(uploaded_audio, topic)
                for k in ("notes", "lesson"):
                    st.session_state.pop(k, None)
            except Exception as e:
                st.session_state.pop("transcript", None)
                st.error(f"Something went wrong: {e}")

if "transcript" in st.session_state:
    st.subheader("Transcript")
    st.caption("Check this against the audio. You can fix mistakes before going on.")
    st.text_area("Transcript", key="transcript", height=250, label_visibility="collapsed")

    if board_photos:
        if st.button("2. Read the board photos"):
            with st.spinner("Reading your photos..."):
                try:
                    st.session_state["board"] = read_board(board_photos, topic)
                    for k in ("notes", "lesson"):
                        st.session_state.pop(k, None)
                except Exception as e:
                    st.session_state.pop("board", None)
                    st.error(f"Something went wrong: {e}")

if "board" in st.session_state and "transcript" in st.session_state:
    st.subheader("Board and slides")
    st.caption("Check this against your photos. You can fix mistakes before making notes.")
    st.text_area("Board", key="board", height=200, label_visibility="collapsed")

if "transcript" in st.session_state:
    if st.button("3. Make notes", type="primary"):
        with st.spinner("Writing notes..."):
            try:
                st.session_state["notes"] = make_notes(
                    st.session_state["transcript"], st.session_state.get("board"), topic
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
    if st.button("4. Teach me this topic"):
        with st.spinner("Preparing your lesson..."):
            try:
                st.session_state["lesson"] = teach(
                    st.session_state["transcript"], st.session_state.get("board"), topic
                )
            except Exception as e:
                st.session_state.pop("lesson", None)
                st.error(f"Something went wrong: {e}")

if "lesson" in st.session_state:
    st.subheader("Lesson (written by AI, not the lecturer)")
    st.warning("AI can make mistakes, especially in maths and physics. Check worked examples and facts in your textbook or with your lecturer.")
    st.markdown(st.session_state["lesson"])

if "transcript" in st.session_state:
    st.divider()
    st.download_button(
        "⬇️ Download everything (one Word file)",
        data=build_full_docx(
            title,
            st.session_state.get("transcript"),
            st.session_state.get("board"),
            st.session_state.get("notes"),
            st.session_state.get("lesson"),
        ),
        file_name=f"{safe}.docx",
        mime=DOCX_MIME,
        type="primary",
    )
    st.caption("The file includes whatever you have made so far.")
