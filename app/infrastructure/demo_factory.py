from app.domain.ai_contract import AiResponse
from app.domain.ports import AIEngine, DocumentRetriever


class DemoAIEngine:
    def answer(self, request, context):
        return AiResponse(
            id="demo-1",
            status="ok",
            answer="Respuesta simulada (demo).",
            claims=[],
            model="demo",
            data_version="demo-v1",
            corpus_version="demo-v1",
        )


class DemoDocumentRetriever:
    def retrieve(self, question, k=5):
        return [{"passage_id": "p1", "text": "pasaje demo", "document_id": "d1", "document_version": "v1", "source_id": "src1"}]


class DemoInfrastructureFactory:
    def ai_engine(self) -> AIEngine:
        return DemoAIEngine()

    def retriever(self) -> DocumentRetriever:
        return DemoDocumentRetriever()
