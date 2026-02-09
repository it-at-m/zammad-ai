import asyncio
import json

import httpx
from dotenv import load_dotenv
from tqdm.asyncio import tqdm_asyncio

from app.core.settings import get_settings
from app.triage.triage import Triage
from app.utils.logging import getLogger

load_dotenv()

logger = getLogger("zammad-ai.benchmark_triage")

# Rate limiting: 50 requests per 30 seconds
RATE_LIMIT = 50
RATE_PERIOD = 30  # seconds

API_BASE_URL = "http://localhost:8080"

settings = get_settings()
triage = Triage(settings=settings)


async def process_item(key: str, value: dict) -> tuple[str, str, str, str]:
    """
    Send an item's text to the triage API and return its expected and predicted category/action.
    
    Parameters:
        key (str): Identifier for the item.
        value (dict): Item payload containing at least "category" (expected category name) and "text" (text to triage).
    
    Returns:
        tuple[str, str, str, str]: A 4-tuple (key, expected_category, predicted_category, predicted_action).
            If an error occurs during the request, `predicted_category` is "Fehler" and `predicted_action` is an empty string.
    """
    expected_category = value["category"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Schritt 1: Triage-Endpunkt aufrufen
        try:
            triage_response = await client.post(f"{API_BASE_URL}/api/triage", json={"text": value["text"]})
            triage_response.raise_for_status()
            result = triage_response.json()
        except Exception:
            return key, expected_category, "Fehler", ""
    predicted_category = result["triage"]["category"]["name"]
    predicted_action = result["triage"]["action"]["name"]

    return key, expected_category, predicted_category, predicted_action


async def run_benchmark():
    correct = {}
    incorrect = {}
    incorrect_categories = {}
    incorrect_but_correct_action = 0
    incorrect_categories_but_correct_action = {}

    # load json
    with open("test/data/benchmark_data.json", "r", encoding="utf-8") as file:
        data = json.load(file)

    # Process items in batches to respect rate limit
    items = list(data.items())
    batch_size = RATE_LIMIT

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        batch_start_time = asyncio.get_event_loop().time()

        # Create tasks for the current batch
        tasks = [process_item(key, value) for key, value in batch]

        # Process batch with progress bar
        results = await tqdm_asyncio.gather(*tasks, desc=f"Processing batch {i // batch_size + 1}")

        # Process results
        for key, expected, predicted, predicted_action in results:
            key_data = data[key]
            key_data["predicted_category"] = predicted
            action = key_data.get("action")
            key_data["predicted_action"] = predicted_action
            if expected == predicted:
                correct[key] = key_data
            else:
                incorrect[key] = key_data
                incorrect_categories[(expected, predicted)] = incorrect_categories.get((expected, predicted), 0) + 1
                if action == predicted_action:
                    incorrect_categories_but_correct_action[(expected, predicted)] = (
                        incorrect_categories_but_correct_action.get((expected, predicted), 0) + 1
                    )
                    incorrect_but_correct_action += 1

        # If there are more batches to process, wait for the rate limit period
        if i + batch_size < len(items):
            batch_end_time = asyncio.get_event_loop().time()
            elapsed = batch_end_time - batch_start_time
            wait_time = RATE_PERIOD - elapsed
            if wait_time > 0:
                logger.info(f"Rate limit: waiting {wait_time:.1f}s before next batch...")
                await asyncio.sleep(wait_time)

    # write results
    with open("test/data/correct_benchmark_results.json", "w", encoding="utf-8") as result_file:
        json.dump(correct, result_file, ensure_ascii=False, indent=4)

    with open("test/data/incorrect_benchmark_results.json", "w", encoding="utf-8") as result_file:
        json.dump(incorrect, result_file, ensure_ascii=False, indent=4)

    with open("test/data/benchmark_results.json", "w", encoding="utf-8") as summary_file:
        all_results = {**correct, **incorrect}
        json.dump(all_results, summary_file, ensure_ascii=False, indent=4)

    total = len(correct) + len(incorrect)
    accuracy = (len(correct) / total) * 100 if total > 0 else 0.0
    logger.info("Total: %d | Correct: %d | Incorrect: %d | Accuracy: %.2f%%", total, len(correct), len(incorrect), accuracy)
    incorrect_categories = dict(sorted(incorrect_categories.items(), key=lambda x: x[1], reverse=True))
    logger.debug("Incorrect category pairs: %s", incorrect_categories)
    logger.debug(
        "Incorrect category pairs but correct action: %d -> Accuracy: %.2f%%",
        incorrect_but_correct_action,
        (len(correct) + incorrect_but_correct_action) / total * 100 if total > 0 else 0.0,
    )
    logger.debug(
        "Incorrect categories (but correct action): %s",
        dict(sorted(incorrect_categories_but_correct_action.items(), key=lambda x: x[1], reverse=True)),
    )

    return accuracy


if __name__ == "__main__":
    accuracy = asyncio.run(run_benchmark())
    assert accuracy >= 70.0, f"Accuracy {accuracy:.2f}% is below the threshold of 70.0%"