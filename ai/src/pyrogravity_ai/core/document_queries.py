"""Recognize catalog shorthand without broadening specific scientific questions."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# Only studies with reviewed documentary sources in the current knowledge base.
_STUDIES = (
    (r"bass\s*(?:ii|2)|psi\s*25|burning and suppression of solids (?:ii|2)",
     "BASS-II", "ntrs:20160000593"),
    (r"flex|psi\s*69|flame extinguishment experiment", "FLEX", "ntrs:20130014061"),
)
_STUDY = "(?:(?:el|la) )?(?:(?:estudio|experimento|investigacion) )?study"
_LINK = "(?:de |del |sobre |acerca de )?"
_TOPICS = (
    (rf"{_STUDY}|(?:hablame|cuentame|dime|explica|informacion) {_LINK}{_STUDY}|"
     rf"que (?:es|fue|estudio|estudiaron|investigo|investigaron) {_STUDY}|"
     rf"que (?:se estudio|se investigo) (?:en )?{_STUDY}|"
     rf"(?:(?:cual(?:es)? (?:es|son|fue|fueron) (?:el|los)) )?"
     rf"(?:objetivos?(?: principales)?|proposito|finalidad) {_LINK}{_STUDY}",
     "What were the main objectives of the {study} investigation?"),
    (rf"(?:resultados?|hallazgos?|conclusiones) {_LINK}{_STUDY}|"
     rf"(?:cuales (?:son|fueron) los (?:resultados|hallazgos) {_LINK}|"
     rf"que (?:descubrio|descubrieron|encontro|encontraron) (?:en )?){_STUDY}",
     "What were the main findings and conclusions reported for the {study} experiment?"),
    (rf"(?:metodologia|metodos?|procedimiento) {_LINK}{_STUDY}|"
     rf"como (?:se (?:hizo|realizo|llevo a cabo)|hicieron|realizaron) {_STUDY}",
     "How was the {study} experiment conducted? What apparatus and procedures were used?"),
    (rf"(?:fuentes?|procedencia|referencias|documentos) {_LINK}{_STUDY}|"
     rf"de donde (?:salen|provienen) los datos {_LINK}{_STUDY}",
     "Which NASA publication documents the {study} experiment? Identify its title and authors."),
    (rf"(?:autores?|responsables|instituciones) {_LINK}{_STUDY}|"
     rf"quien(?:es)? (?:realizo|realizaron|hizo|hicieron) {_STUDY}",
     "Who conducted or documented the {study} investigation? Identify named authors or institutions."),
)
_MISSING_STUDY = re.compile(
    r"que (?:investigaron|descubrieron|encontraron)|cuales fueron los resultados|"
    r"como hicieron la investigacion|quien realizo el estudio|de donde salen estos datos"
)


@dataclass(frozen=True)
class DocumentQuery:
    question: str | None
    source_ids: tuple[str, ...]
    needs_study: bool = False


def interpret_document_query(question: str) -> DocumentQuery:
    folded = unicodedata.normalize("NFKD", question.casefold())
    normalized = " ".join(re.findall(r"[^\W_]+", "".join(
        char for char in folded if not unicodedata.combining(char)
    )))
    studies = []
    for aliases, name, source in _STUDIES:
        normalized, matches = re.subn(rf"\b(?:{aliases})\b", " study ", normalized)
        if matches:
            studies.append((name, source))
    sources = tuple(source for _, source in studies)
    normalized = " ".join(normalized.split())
    if len(studies) == 1:
        for pattern, template in _TOPICS:
            if re.fullmatch(pattern, normalized):
                return DocumentQuery(template.format(study=studies[0][0]), sources)
    return DocumentQuery(None, sources, bool(_MISSING_STUDY.fullmatch(normalized)))
