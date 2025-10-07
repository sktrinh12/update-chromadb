import json
import chromadb
from chromadb.utils import embedding_functions

INPUT_FILE = "workitems_cleaned.json"

def load_cleaned_data(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    client = chromadb.PersistentClient(path="./chroma")

    embedding_func = embedding_functions.DefaultEmbeddingFunction()

    collection = client.get_or_create_collection(
        name="workitems",
        embedding_function=embedding_func
    )

    records = load_cleaned_data(INPUT_FILE)

    # Upload documents into Chroma
    for rec in records:
        collection.add(
            documents=[rec["embedding_text"]],
            metadatas=[rec["metadata"]],
            ids=[f"{rec['id']}_{rec['chunk_index']}"]
        )

    print(f"Uploaded {len(records)} records into Chroma collection 'workitems'.")


if __name__ == "__main__":
    main()
