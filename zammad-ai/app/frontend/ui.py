from typing import Any

import gradio as gr
import httpx

from app.settings.frontend import FrontendSettings
from app.utils.logging import getLogger

logger = getLogger("zammad-ai.frontend")

FrontendResult = tuple[str, str, str, str, str, str]

API_BASE_URL = "http://localhost:8080"
EXAMPLE_PAYLOADS: list[tuple[str, str]] = [
    (
        "MA_beantwortet",
        "Guten Tag, unter folgendem Link finden Sie alle Informationen rund um den internationalen Führerschein: Dort können Sie auch direkt online einen Antrag stellen. Alternativ können Sie einen Termin vereinbaren und sich den internationalen Führerschein Vorort ausstellen lassen: Mit freundlichen Grüßen",
    ),
    (
        "Fragen",
        "Sehr geehrte Damen und Herren, wie im Anhang zu sehen ist habe ich eine Bestätigung der bestandenen Praxisprüfung erhalten, mit der ich aber anscheinend noch nicht fahren darf. Muss ich für die Prüfungsbescheinigung für begleitetes Fahren ein Termin ausmachen, weil alle anderen haben diese Bescheinigung eigentlich am Tag ihrer Prüfung direkt erhalten. Mit freundlichen Grüssen Straße",
    ),
    (
        "Terminanfrage",
        "Sehr geehrten Damen und Herren ich möchte gerne einen Termin für den umtausch meiner Führerschein. Mit freundichen Grüßen",
    ),
    (
        "Anfrage_Bearbeitungsstand",
        "Sehr geehrte Damen und Herren, bis wann ist denn mit der Bearbeitung des Umtausches zu rechnen? Ich würde gern im kommenden Urlaub einen gültigen Führerschein bei mir haben. Danke und freundliche Grüße",
    ),
    (
        "Zuordnung nicht möglich",
        'Hallo, Ihre EMail mit dem Betreff "Führerschein" konnte leider nicht an einen oder mehrere Empfänger zugestellt werden. Die Nachricht hatte eine Größe von 14.99 MB, wir akzeptieren jedoch nur EMails mit einer Größe von bis zu 10 MB. Bitte reduzieren Sie die Größe Ihrer Nachricht und versuchen Sie es erneut. Vielen Dank für Ihr Verständnis. Mit freundlichen Grüßen Postmaster von dbszammad.muenchen.de',
    ),
    (
        "Nachreichung",
        "Hallo wie telefonisch vereinbart sende ich Ihnen die Bestätigung des Zertifikates zu. Zu dem wollte ich mich nochmals entschuldigen mich so spät gemeldet zu haben da meine aktuelle Lebenssituation nicht auf dem graden weg ist. Aktuell wohne ich nichtmehr bei meinen eltern sondern übernachte bei meiner Freundin. Ich hoffe das ich mein Zertifikat schnellst möglich bekomme und ihnen das direkt zu senden kann. Denn der Führerschein ist lebensnotwendig für mich. Mit freundlichen Grüßen",
    ),
]


def _empty_result(message: str = "") -> FrontendResult:
    """
    Create a FrontendResult populated with a head message and empty fields.

    Parameters:
        message (str): Text to place in the first element (typically an informational or error message).

    Returns:
        FrontendResult: A 6-tuple of strings in the order (category, action, reasoning, confidence, answer, answer_documents)
        where only the first element contains `message` and the remaining five are empty strings.
    """
    return message, "", "", "", "", ""


def _format_documents(documents: list[dict[str, Any]]) -> str:
    """
    Format a list of document dictionaries into a single newline-separated string.

    Parameters:
        documents (list[dict[str, Any]]): A list of document objects represented as dictionaries.

    Returns:
        str: A single string with each document's string representation on its own line, or an empty string if `documents` is empty.
    """
    if not documents:
        return ""
    return "\n".join(str(document) for document in documents)


async def _request_json(client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Send a JSON POST to the given URL and return the parsed JSON object.

    Sends `payload` as the request JSON using `client.post`, ensures the HTTP response status is successful, parses the response body as JSON, and verifies the parsed value is a dict.

    Parameters:
        client (httpx.AsyncClient): Async HTTP client used to perform the request.
        url (str): Target URL for the POST request.
        payload (dict[str, Any]): JSON-serializable payload to send in the request body.

    Returns:
        dict[str, Any]: The parsed JSON object from the response.

    Raises:
        httpx.HTTPStatusError: If the response status is not successful (`raise_for_status()`).
        ValueError: If the response JSON is not an object (dict).
    """
    response = await client.post(url=url, json=payload)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        msg = f"Expected JSON object from {url}, got {type(data).__name__}"
        raise ValueError(msg)
    return data


async def process_ticket(text: str, *, api_base_url: str, timeout_seconds: float) -> FrontendResult:
    """
    Process ticket text through triage and, if the triage action indicates, request an AI-generated answer.

    Sends the ticket text to the triage endpoint and extracts category, action, reasoning, and confidence. If the triage action is "AI_Answer" or "ai_response", requests an answer and any supporting documents from the answer endpoint and formats them for the frontend.

    Parameters:
        api_base_url (str): Base URL of the backend API (e.g., "http://localhost:8080").
        timeout_seconds (float): HTTP request timeout in seconds.

    Returns:
        FrontendResult: A 6-tuple (category, action, reasoning, confidence, answer, answer_documents)
            - category (str): Detected ticket category (or "Unbekannt").
            - action (str): Determined action name.
            - reasoning (str): Explanation or reasoning from triage.
            - confidence (str): Confidence as a percentage string (e.g., "87.5%").
            - answer (str): AI-generated answer when available, otherwise an empty string or error message.
            - answer_documents (str): Formatted supporting documents joined by newlines, or empty string.

    Raises:
        gr.Error: If the input text is empty or triage encounters a connection, timeout, HTTP, or other fatal error.
    """
    if not text.strip():
        raise gr.Error("Keine Eingabe")

    triage_url = f"{api_base_url}/api/v1/triage"
    answer_url = f"{api_base_url}/api/v1/answer"

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        try:
            triage_data = await _request_json(client=client, url=triage_url, payload={"text": text})
        except httpx.ConnectError:
            raise gr.Error(f"Verbindungsfehler: Backend läuft nicht auf {api_base_url}")
        except httpx.TimeoutException:
            raise gr.Error("Timeout: Triage dauert zu lange")
        except httpx.HTTPStatusError as e:
            raise gr.Error(f"HTTP-Fehler {e.response.status_code}: {e.response.text}")
        except Exception as e:
            logger.error("Failed to process triage request.", exc_info=True, extra={"exception_type": type(e).__name__})
            raise gr.Error("Fehler bei Triage")

        triage_result = triage_data.get("triage", {})
        session_id = triage_data.get("id")

        category = triage_result.get("category", {}).get("name", "Unbekannt")
        action = str(triage_result.get("action", {}).get("name", "Unbekannt"))
        reasoning = triage_result.get("reasoning", "")
        confidence = float(triage_result.get("confidence", 0.0))

        answer = ""
        answer_documents = ""

        try:
            answer_data = await _request_json(
                client=client,
                url=answer_url,
                payload={
                    "text": text,
                    "category": category,
                    "session_id": session_id,
                    "action": action,
                },
            )
            answer = str(answer_data.get("response", ""))
            documents = answer_data.get("documents", [])
            if isinstance(documents, list):
                answer_documents = _format_documents(documents=documents)
        except httpx.ConnectError:
            gr.Warning(f"Verbindungsfehler bei Answer: Backend läuft nicht auf {api_base_url}")
            answer = "Fehler bei Answer-Generierung"
        except httpx.TimeoutException:
            gr.Warning("Timeout: Answer-Generierung dauert zu lange")
            answer = "Fehler bei Answer-Generierung"
        except httpx.HTTPStatusError as e:
            gr.Warning(f"HTTP-Fehler {e.response.status_code}: {e.response.text}")
            answer = "Fehler bei Answer-Generierung"
        except Exception as e:
            logger.error("Failed to process answer request.", exc_info=True, extra={"exception_type": type(e).__name__})
            gr.Warning("Fehler bei Answer-Generierung")
            answer = "Fehler bei Answer-Generierung"

    confidence_str = f"{confidence * 100:.1f}%"
    return category, action, reasoning, confidence_str, answer, answer_documents


def build_frontend(frontend_settings: FrontendSettings) -> gr.Blocks:
    """Build the Gradio frontend Blocks UI."""

    async def _process_ticket(text: str) -> FrontendResult:
        """
        Process the given ticket text using the module's configured API base URL and the frontend's request timeout.

        Parameters:
            text (str): Raw ticket text to be analyzed and (optionally) answered.

        Returns:
            tuple[str, str, str, str, str, str]: A 6-tuple containing
                (category, action, reasoning, confidence, answer, answer_documents).
                `confidence` is formatted as a percentage string with one decimal place (e.g., "87.5%").
        """
        return await process_ticket(
            text=text,
            api_base_url=API_BASE_URL,
            timeout_seconds=frontend_settings.request_timeout_seconds,
        )

    with gr.Blocks(title="Zammad AI Triage Demo") as frontend:
        gr.Markdown("# Zammad AI Triage & Answer Demo")
        gr.Markdown("Geben Sie einen Ticket-Text ein, um die KI-gestützte Triage und Antwortgenerierung zu testen.")

        with gr.Row():
            with gr.Column():
                gr.Markdown("### Eingabe")
                input_text = gr.Textbox(label="Ticket-Text", placeholder="Geben Sie hier Ihre Anfrage ein...", lines=10)
                submit_btn = gr.Button("Absenden", variant="primary")

                gr.Markdown("### Beispiele")
                with gr.Row():
                    for label, payload in EXAMPLE_PAYLOADS[:2]:
                        gr.Button(label, size="sm").click(lambda text=payload: text, outputs=input_text)
                with gr.Row():
                    for label, payload in EXAMPLE_PAYLOADS[2:4]:
                        gr.Button(label, size="sm").click(lambda text=payload: text, outputs=input_text)
                with gr.Row():
                    for label, payload in EXAMPLE_PAYLOADS[4:6]:
                        gr.Button(label, size="sm").click(lambda text=payload: text, outputs=input_text)

            with gr.Column():
                gr.Markdown("### Ergebnisse")
                category_output = gr.Textbox(label="Category", interactive=False)
                action_output = gr.Textbox(label="Action", interactive=False)
                reasoning_output = gr.Textbox(label="Reasoning", interactive=False, lines=3)
                confidence_output = gr.Textbox(label="Confidence", interactive=False)
                answer_output = gr.Textbox(label="KI-Antwort", interactive=False, lines=12)
                answer_documents_output = gr.Textbox(label="Answer Documents", interactive=False, lines=20)

        outputs = [
            category_output,
            action_output,
            reasoning_output,
            confidence_output,
            answer_output,
            answer_documents_output,
        ]

        submit_btn.click(fn=_process_ticket, inputs=[input_text], outputs=outputs)
        input_text.submit(fn=_process_ticket, inputs=[input_text], outputs=outputs)

    return frontend
