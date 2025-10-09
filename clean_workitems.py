import json
import re
import os
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

MAX_CHUNK_WORDS = 500
COMMENT_CHUNK_WORDS = 200  # finer-grained chunks for comments

# Mapping of DevOps mentions to human-readable names
MENTION_MAP = {
    "000BFF27-0E57-6097-BD33-8C7CBEEC3268": "Trinh, Spencer",
    "6186434E-47E8-63CD-B72F-A71288EB6D56": "Genaro Scavello",
    "6711815B-219C-6B1C-9514-D17377935077": "Min Wang",
    "7AC86A0C-3597-6C88-912D-2A2BF600C6B1": "Raul Leal",
    "CEBDFF88-616E-665A-BF1A-B85A0CBB30EE": "Amy Crossan",
}

def replace_mention(match):
    mention_id = match.group(1)
    return MENTION_MAP.get(mention_id, "[UNKNOWN]")

def markdown_table_to_sentences(text: str) -> str:
    """
    Convert markdown tables into natural language sentences for embeddings.
    Example:
    |ISID|ROLE|COMPONENT|
    |DBEAM|ADMIN|STORAGE_MANAGER|
    =>
    "Row: ISID = DBEAM, ROLE = ADMIN, COMPONENT = STORAGE_MANAGER."
    """
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return text  # not a valid table, return unchanged

    # Extract headers
    headers = [h.strip() for h in lines[0].strip("|").split("|")]

    sentences = []
    # Process each data row
    for row in lines[2:]:  # skip header + separator
        values = [v.strip() for v in row.strip("|").split("|")]
        if len(values) != len(headers):
            continue
        kv_pairs = [f"{h} = {v}" for h, v in zip(headers, values)]
        sentences.append("Row: " + ", ".join(kv_pairs) + ".")

    return " ".join(sentences)

def replace_file_links(text: str) -> str:
    """Replace DevOps attachment links with placeholders."""
    def repl(match):
        link_text = match.group(1)
        url = match.group(2)
        if "_apis/wit/attachments/" in url and "fileName=" in url:
            file_name = url.split("fileName=")[-1].split("&")[0]
            return f"[FILE: {file_name}]"
        else:
            return f"{link_text}"  # keep readable text
    return re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', repl, text)

def replace_markdown_links(text: str) -> str:
    """Replace markdown links [text](url) with [LINK: text] placeholders."""
    def repl(match):
        link_text = match.group(1).strip()
        return f"[LINK: {link_text}]"
    return re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', repl, text)

def replace_urls(text: str) -> str:
    """Replace remaining raw URLs with [LINK]."""
    return re.sub(r'https?://\S+', '[LINK]', text)

def remove_horizontal_rules(text: str) -> str:
    """Remove Markdown horizontal rules (`---`)."""
    return re.sub(r'\n?-{3,}\n?', ' ', text)

def strip_latex_math(text: str) -> str:
    """
    Remove $$...$$ or $...$ delimiters from LaTeX math blocks,
    keeping the math content inside.
    """
    # Remove $$...$$ blocks
    text = re.sub(r'\$\$(.+?)\$\$', r'\1', text, flags=re.DOTALL)
    # Remove inline $...$ blocks
    text = re.sub(r'\$(.+?)\$', r'\1', text)
    return text

def clean_text(text: str) -> str:
    """Clean HTML, markdown, mentions, images, tables, code, math, and links."""
    if not text:
        return ""
    
    # Convert HTML entities to text
    text = BeautifulSoup(text, "html.parser").get_text(separator=" ")

    # Replace mentions, and replace @ symbols
    text = re.sub(
        r'@',
        '',
        re.sub(r'@<([\w-]+)>', replace_mention, text)
    )

    # Replace markdown images
    text = re.sub(r'!\[.*?\]\(.*?\)', '[IMAGE]', text)

    # Flatten markdown tables
    text = markdown_table_to_sentences(text)

    # Replace markdown links with [LINK: text]
    text = replace_markdown_links(text)

    # Replace remaining raw URLs
    text = replace_urls(text)

    # Remove horizontal rules
    text = remove_horizontal_rules(text)

    # Strip LaTeX math $$...$$
    text = strip_latex_math(text)

    # Replace common LaTeX symbols with plain-text equivalents
    latex_symbols = {
        r'\\leq': '<=',
        r'\\geq': '>=',
        r'\\times': '*',
        r'\\cdot': '*',
        r'\\pm': '+/-',
        r'\\neq': '!=',
        r'\\approx': '~',
        r'\\to': '->',
    }
    for k, v in latex_symbols.items():
        text = re.sub(k, v, text)

    # Remove \text{...} commands but keep content
    text = re.sub(r'\\text\{(.+?)\}', r'\1', text)
    # Remove inline code markers and extra symbols
    text = re.sub(r'`(.+?)`', r'\1', text)

    # Remove JSON-like braces that are not meaningful
    text = re.sub(r'[{}]', '', text)

    # Remove extra markdown symbols
    text = re.sub(r'\*+|\#+|>', '', text)

    # Remove markdown horizontal rules "---"
    text = re.sub(r'---+', ' ', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text

def chunk_text(text: str, max_words: int) -> list:
    """Split text into chunks of approximately max_words each."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i:i+max_words]))
    return chunks

def prepare_embedding_text(workitem: dict) -> list:
    """
    Convert workitem fields into embedding-ready text chunks with metadata.
    - Main text (title, description, acceptance criteria) is chunked together
    - Each comment is chunked separately at COMMENT_CHUNK_WORDS
    """
    records = []

    # === MAIN WORK ITEM BODY ===
    parts = []

    # Add cleaned title as natural text
    title = workitem.get("title", "")
    if title:
        parts.append(title)

    # Add description and acceptance criteria
    description = clean_text(workitem.get("description", ""))
    if description:
        parts.append(description)

    acceptance = clean_text(workitem.get("acceptance_criteria", ""))
    if acceptance:
        parts.append(acceptance)

    # Join all into one blob
    full_text = "\n".join(parts)

    # Chunk the main text
    for idx, chunk in enumerate(chunk_text(full_text, max_words=MAX_CHUNK_WORDS)):
        records.append({
            "id": workitem.get("id"),
            "chunk_index": idx,
            "embedding_text": chunk,
            "metadata": {
                "title": title,
                "section": "main",
                "description": description,
                "acceptance_criteria": acceptance,
                "type": workitem.get("type"),
                "state": workitem.get("state"),
                "assignedTo": workitem.get("assignedTo") or "",
                "storyPoints": workitem.get("story_points") or 0,
                "tags": workitem.get("tags") or "",
                "createdDate": workitem.get("createdDate", ""),
                "changedDate": workitem.get("changedDate", "")
            }
        })

    # === COMMENTS ===
    comments = workitem.get("comments", [])
    for idx, c in enumerate(comments):
        author = c.get("createdBy", {}).get("displayName", "Unknown")
        iso_str = c.get("createdDate", "")
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        date = dt.strftime("%B %d, %Y at %H:%M UTC")  
        iso_str = c.get("modifiedDate", "")
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        mod_date = dt.strftime("%B %d, %Y at %H:%M UTC")
        text = clean_text(c.get("text", ""))

        if not text:
            continue

        # Chunk each comment separately
        for jdx, chunk in enumerate(chunk_text(text, max_words=COMMENT_CHUNK_WORDS)):
            records.append({
                "id": workitem.get("id"),
                "chunk_index": f"c{idx}_{jdx}",  # distinguish comment chunks
                "embedding_text": f"{author} commented on ({date}): {chunk}",
                "metadata": {
                    "title": title,
                    "section": "comment",
                    "description": description,
                    "acceptance_criteria": acceptance,
                    "author": author,
                    "createdDate": date,
                    "modifiedDate": mod_date, 
                    "type": workitem.get("type"),
                    "state": workitem.get("state"),
                    "assignedTo": workitem.get("assignedTo") or "",
                    "storyPoints": workitem.get("story_points") or 0,
                    "tags": workitem.get("tags") or ""
                }
            })

    return records

def process_workitems(input_file: str, output_file: str = None) -> list:
    """Load, clean, chunk workitems, and return list ready for vector embedding."""
    input_path = Path(input_file)
    if not input_path.is_file():
        raise FileNotFoundError(f"{input_file} not found")

    with open(input_file, "r", encoding="utf-8") as f:
        workitems = json.load(f)

    processed_records = []
    for wi in workitems:
        # prepare_embedding_text now returns a list of full records
        processed_records.extend(prepare_embedding_text(wi))

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(processed_records, f, indent=2, ensure_ascii=False)

    return processed_records


if __name__ == "__main__":
    in_path = os.getenv("WORKITEMS_FILE")
    out_path = f"{in_path.split('.')[0]}_cleaned.json"
    processed = process_workitems(in_path, out_path)
    print(f"Processed {len(processed)} workitems from {out_path}")
