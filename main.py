import streamlit as st
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import os
from google import genai
import re

# --- Gemini API ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# --- Streamlit UI ---
st.set_page_config(page_title="arXiv Daily Digest", layout="wide")
st.markdown("<h1 style='text-align:center;'>📰 arXiv Daily AI/ML Digest</h1>", unsafe_allow_html=True)
st.markdown("Latest AI & ML research summarized. Select a knowledge level to adjust the summary.")

# --- Parameters ---
CATEGORIES = ["cs.AI","cs.LG","cs.CV"]

# Friendly names for display
CATEGORY_NAMES = {
    "cs.AI": "AI 🤖",
    "cs.LG": "ML 🧠",
    "cs.CV": "CV 👁️"
}
# Reverse mapping for internal filtering
FRIENDLY_TO_CODE = {v: k for k, v in CATEGORY_NAMES.items()}

# --- Fetch arXiv papers ---
@st.cache_data(ttl=3600)
def fetch_arxiv_papers(max_results=10, days_back=1):
    query = " OR ".join([f"cat:{c}" for c in CATEGORIES])
    url = f"http://export.arxiv.org/api/query?search_query={query}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    
    response = requests.get(url)
    if response.status_code != 200:
        st.error("Failed to fetch papers from arXiv")
        return []
    
    root = ET.fromstring(response.text)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    papers = []
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    
    for entry in root.findall('atom:entry', ns):
        published_dt = datetime.fromisoformat(entry.find('atom:published', ns).text.rstrip('Z'))
        if published_dt < cutoff:
            continue
        
        arxiv_id = entry.find('atom:id', ns).text.split('/abs/')[-1]
        title = entry.find('atom:title', ns).text.strip().replace('\n',' ')
        summary = entry.find('atom:summary', ns).text.strip().replace('\n',' ')
        authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
        categories = [c.attrib['term'] for c in entry.findall('atom:category', ns)]
        
        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "summary": summary,
            "published": published_dt.strftime("%Y-%m-%d"),
            "authors": authors,
            "categories": categories,
            "pdf_link": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            "abstract_link": f"https://arxiv.org/abs/{arxiv_id}"
        })
    return papers

# --- Regex parser for consistent output ---
def parse_summary(response_text):
    sections = ["Overall Summary", "High School", "Bachelors", "Masters", "Expert", "Key Points"]
    summaries = {}

    pattern = r"(## (?P<section>.+?))\s*\n(?P<content>.*?)(?=\n## |$)"
    matches = re.finditer(pattern, response_text, re.DOTALL | re.IGNORECASE)

    for m in matches:
        section = m.group("section").strip()
        content = m.group("content").strip()
        if section in sections:
            summaries[section] = content

    # Ensure all sections exist
    for sec in sections:
        if sec not in summaries:
            summaries[sec] = ""

    return summaries

# --- Generate summary for a paper ---
@st.cache_data(show_spinner=False)
def generate_summary(paper):
    prompt = f"""
You are an expert science communicator. Summarize the following AI/ML paper using **clear markdown headings**.

## Overall Summary
2–3 sentences summarizing the paper concisely.

## High School
2–3 sentences, very simple, no jargon.

## Bachelors
2–3 sentences, clear technical explanation.

## Masters
2–3 concise technical sentences.

## Expert
2–3 precise technical sentences for an expert audience.

## Key Points
3 bullet points highlighting main contributions, method, and outcome.

Abstract:
{paper['summary']}
"""
    try:
        response_text = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        ).text.strip()
        summaries = parse_summary(response_text)
    except Exception as e:
        st.warning(f"Gemini API error: {e}")
        fallback = '. '.join(paper['summary'].split('. ')[:2]) + '.'
        summaries = {level: fallback for level in ["Overall Summary", "High School", "Bachelors", "Masters", "Expert", "Key Points"]}
    return summaries

# --- Sidebar Filters ---
st.sidebar.header("Settings")
num_papers = st.sidebar.slider("Number of papers", 3, 15, 5)
days_back = st.sidebar.slider("Show papers from last (days)", 1, 7, 3)

# Friendly category multiselect
friendly_default = [CATEGORY_NAMES[c] for c in CATEGORIES]
selected_friendly = st.sidebar.multiselect(
    "Filter by category",
    options=list(CATEGORY_NAMES.values()),
    default=friendly_default
)
category_filter = [FRIENDLY_TO_CODE[f] for f in selected_friendly]

# --- Fetch and filter papers ---
papers = fetch_arxiv_papers(max_results=num_papers, days_back=days_back)
filtered_papers = [p for p in papers if any(cat in category_filter for cat in p['categories'])]
st.metric("Papers fetched", len(filtered_papers))

# --- Display Papers ---
for paper in filtered_papers:
    with st.container():
        st.markdown(f"## {paper['title']}")
        st.markdown(f"**Authors:** {', '.join(paper['authors'][:3])}{' et al.' if len(paper['authors'])>3 else ''}")
        st.markdown(f"**Published:** {paper['published']}")
        st.markdown(" ".join([
            f"<span style='background-color:#DDEBF7;padding:3px 8px;border-radius:5px;margin-right:5px;font-size:12px'>{CATEGORY_NAMES.get(cat, cat)}</span>" 
            for cat in paper['categories']
        ]), unsafe_allow_html=True)
        
        summaries = generate_summary(paper)
        
        # Knowledge level dropdown
        level = st.selectbox(
            "Select summary level:",
            ["Overall Summary", "High School", "Bachelors", "Masters", "Expert"],
            key=paper['arxiv_id']
        )
        st.markdown(summaries.get(level, ""))
        
        # Key points (always visible)
        st.markdown("**Key points:**")
        st.markdown(summaries.get("Key Points", ""))
        
        # Links
        st.markdown(f"📄 [PDF]({paper['pdf_link']}) | 🌐 [Abstract]({paper['abstract_link']})")
        st.markdown("---")
