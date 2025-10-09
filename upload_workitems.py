import json
import os
import chromadb
from chromadb.utils import embedding_functions

INPUT_FILE = os.getenv("INPUT_FILE")
CHROMA_DIR = os.getenv("CHROMA_DIR")

def load_cleaned_data(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    embedding_func = embedding_functions.DefaultEmbeddingFunction()

    collection = client.get_or_create_collection(
        name="workitems",
        embedding_function=embedding_func
    )

    records = load_cleaned_data(INPUT_FILE)

    for rec in records:
        rec_id = f"{rec['id']}_{rec['chunk_index']}"
        collection.upsert(
            documents=[rec["embedding_text"]],
            metadatas=[rec["metadata"]],
            ids=[rec_id]
        )
        print(f"Upserted record {rec_id}")

    print(f"Uploaded {len(records)} records into Chroma collection 'workitems'")


if __name__ == "__main__":
    main()
