from django.shortcuts import render
from django.shortcuts import render
from chat.answer import answer_question


def home(request):
    answer = ""
    question = ""
    event = "cyclone_ditwah"

    if request.method == "POST":
        question = request.POST.get("question", "").strip()
        event = request.POST.get("event", "cyclone_ditwah")

        if event not in ("cyclone_ditwah", "valencia_dana"):
            event = "cyclone_ditwah"

        if question:
            try:
                answer = answer_question(question, event=event)
            except Exception:
                answer = "Unable to generate an answer. Please try again."

    return render(request, "chatbot/home.html", {
        "answer": answer,
        "question": question,
        "event": event,
    })
