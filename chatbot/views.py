from django.shortcuts import render

from chat.answer import generate_answer


def home(request):
    answer = ""
    sources = []
    cited = False
    question = ""
    event = "cyclone_ditwah"

    if request.method == "POST":
        question = request.POST.get("question", "").strip()
        event = request.POST.get("event", "cyclone_ditwah")

        if event not in ("cyclone_ditwah", "valencia_dana"):
            event = "cyclone_ditwah"

        if question:
            try:
                result = generate_answer(question, event=event)
                answer, sources, cited = result.text, result.sources, result.cited
            except Exception:
                answer = "Unable to generate an answer. Please try again."

    return render(request, "chatbot/home.html", {
        "answer": answer,
        "sources": sources,      # documents the answer was generated from (User Story 4)
        "cited": cited,          # False: retrieved for the question but not cited in the answer
        "question": question,
        "event": event,
    })
