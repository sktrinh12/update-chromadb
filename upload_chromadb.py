import json
import chromadb
from chromadb.utils import embedding_functions
from collections import defaultdict

INPUT_FILE = os.getenv("INPUT_FILE")

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

    grouped = defaultdict(list)
    for rec in records:
        grouped[rec["id"]].append(rec)

    for wid, recs in grouped.items():
        # Try to delete existing embeddings for this work item
        try:
            existing_ids = [
                item["id"] for item in collection.get(include=["metadatas", "documents"], where={"id": wid})["ids"]
            ]
            if existing_ids:
                collection.delete(ids=existing_ids)
                print(f"Deleted {len(existing_ids)} existing entries for WorkItem {wid}")
        except Exception:
            # Some Chroma backends don’t support `where` filtering on metadata.id, so fallback:
            pass

        collection.add(
            documents=[rec["embedding_text"]],
            metadatas=[rec["metadata"]],
            ids=[f"{rec['id']}_{rec['chunk_index']}"]
        )
        print(f"Added {len(recs)} records for WorkItem {wid}")

    print(f"Uploaded {len(records)} records into Chroma collection 'workitems'.")


if __name__ == "__main__":
    main()
