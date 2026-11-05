import io
import os
import re
import tempfile

import streamlit as st
from docx import Document
from google import genai

MODEL = "gemini-flash-latest"

st.set_page_config(page_title="Lecture Notes", page_icon="📝")
st.title("📝 Lecture Notes")
st.write("Upload a lecture recording and get study notes you can download.")


@st.cache_resource
def get_client():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])


def build_docx(title, notes):
    doc = Document()
    doc.add_heading(title, 0)
    for line in notes.split("\n"):
        line = line.strip()
        if not line:
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


def make_notes(audio_file, topic):
    client = get_client()
    suffix = os.path.splitext(audio_file.name)[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(audio_file.getvalue())
        path = tmp.name
    try:
        uploaded = client.files.upload(file=path)
        prompt = f"""You are a student note-taker. Listen to this lecture and write clear study notes.
Course/topic: {topic}

Use headings, bullet points, key terms with short definitions, and a short summary at the end.
Only use what the lecturer actually said. If something is unclear, say so instead of guessing."""
        response = client.models.generate_content(
            model=MODEL, contents=[prompt, uploaded]
        )
        return response.text
    finally:
        os.remove(path)


uploaded_audio = st.file_uploader(
    "Upload lecture audio", type=["mp3", "wav", "m4a", "aac", "ogg"]
)
topic = st.text_input("Course / topic (helps accuracy)")
title = st.text_input("Title for your notes", value="Lecture Notes")

if st.button("Make notes", type="primary"):
    if uploaded_audio is None:
        st.warning("Please upload an audio file first.")
    else:
        with st.spinner("Listening and writing notes... this can take a few minutes."):
            try:
                st.session_state["notes"] = make_notes(uploaded_audio, topic)
                st.session_state["title"] = title or "Lecture Notes"
            except Exception as e:
                st.session_state.pop("notes", None)
                st.error(f"Something went wrong: {e}")

if "notes" in st.session_state:
    notes = st.session_state["notes"]
    note_title = st.session_state["title"]
    st.markdown(notes)
    safe = re.sub(r"[^\w\- ]", "", note_title).strip() or "lecture_notes"
    st.download_button(
        "Download notes (Word)",
        data=build_docx(note_title, notes),
        file_name=f"{safe}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
