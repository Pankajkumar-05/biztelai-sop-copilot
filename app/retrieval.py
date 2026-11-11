"""TF-IDF retrieval with a revision filter and a 'not found' gate.

Plain-words version: each section is scored by how many of the question's *rare* words it contains
(rare words like AL-104 count more than common ones). Only CURRENT chunks can become evidence.
Superseded chunks are scored too, but only so the app can add a note that an older revision exists.
"""
import re
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer

from . import config
from .ingest import Chunk, Corpus

STOP_WORDS = set(
    "a an and are as at be been by can could did do does for from has have how i if in is it its me my "
    "of on or our should so than that the their them then there these they this to us was we were what "
    "when where which who whom why will with would you your tell please".split()
)
# Words that say HOW the question is asked, not WHAT it is about ("how often", "how many", "recommended").
# They would otherwise count as unmatched topic words and make good questions look unsupported.
REQUEST_WORDS = set(
    "recommend recommended show shown shows often quickly many much happen happens long required require "
    "requirement requirements need needed go used use using allowed".split()
)

# Different ways of asking for the same thing, mapped to the word the documents use (applied after stemming).
# Without this, "coolant mix percentage" cannot find "Coolant concentration".
SYNONYMS = {
    "mix": "concentration", "mixtur": "concentration", "percentag": "concentration", "percent": "concentration",
    "ratio": "concentration", "dilution": "concentration",
    "notifi": "inform", "notify": "inform", "notific": "inform",
}

CODE_RE = re.compile(r"\b([a-z]{2,4})[\s-]?(\d{2,4}[a-z]?)\b")
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-.][a-z0-9]+)*")
CODE_TOKEN_RE = re.compile(r"^[a-z]{1,4}(?:-[a-z]{1,4})*-\d+[a-z]?$")   # al-104, bh-220, qc-sop-014, qf-07a


def stem(word: str) -> str:
    """Very small suffix stripper: checked/checking/check, centre/centres, change/changed all meet."""
    if len(word) < 5 or any(ch.isdigit() for ch in word):
        return word
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    else:
        if word.endswith("ies"):
            word = word[:-3] + "y"
        elif word.endswith("es") and len(word) > 4 and word[-3] in "sxz":
            word = word[:-2]
        elif word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
    if word.endswith("e") and len(word) >= 5:
        word = word[:-1]
    return word


class TextAnalyzer:
    """Lower-case, keep codes whole (al-104, bh-220), fix 'AL104' / 'AL 104' -> 'al-104', drop stop words, stem."""

    def __init__(self, code_prefixes: set[str]):
        self.code_prefixes = code_prefixes

    @staticmethod
    def find_prefixes(texts: list[str]) -> set[str]:
        prefixes = set()
        for text in texts:
            for match in re.finditer(r"\b([a-z]{2,4})-(\d{2,4}[a-z]?)\b", text.lower()):
                prefixes.add(match.group(1))
        return prefixes

    def normalize(self, text: str) -> str:
        def fix(match: re.Match) -> str:
            # Only join letters+digits when the letters are a code prefix that exists in the documents,
            # so "lot of 200" is not turned into "of-200".
            if match.group(1) in self.code_prefixes:
                return f"{match.group(1)}-{match.group(2)}"
            return match.group(0)

        return CODE_RE.sub(fix, text.lower())

    def tokens(self, text: str) -> list[str]:
        words = []
        for token in TOKEN_RE.findall(self.normalize(text)):
            # Codes (al-104, qc-sop-014) stay whole; other hyphenated words are split ("200-piece" -> 200, piece).
            words.extend([token] if CODE_TOKEN_RE.match(token) else token.split("-"))
        kept = [w for w in words if (w not in STOP_WORDS and w not in REQUEST_WORDS and len(w) > 1) or w.isdigit()]
        stemmed = [SYNONYMS.get(t, t) for t in (stem(w) for w in kept)]
        return [t for t in stemmed if t not in REQUEST_WORDS]   # "showing" -> "show" is a request word too


@dataclass
class Hit:
    chunk: Chunk
    score: float


@dataclass
class SearchResult:
    current_hits: list[Hit]       # best CURRENT chunks, best first (the only possible evidence)
    superseded_hits: list[Hit]    # older-revision chunks that match the question itself (strict: same gate rules)
    older_versions: list[Hit]     # superseded_hits + older chunks of the same document that score close to the
                                  # best current chunk, i.e. "the old version of what we are about to cite"
    top_score: float
    coverage: float               # best share of the question's meaningful words found in any of the top 3 chunks
    query_terms: list[str]
    is_vague: bool
    unknown_terms: list[str]      # question words that appear nowhere in any supplied document


class Index:
    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        self.current = corpus.current_chunks()
        self.superseded = corpus.superseded_chunks()
        texts = [c.text for c in corpus.chunks]
        self.analyzer = TextAnalyzer(TextAnalyzer.find_prefixes(texts))
        # Fit on CURRENT chunks only; superseded chunks are scored with the same vocabulary.
        self.vectorizer = TfidfVectorizer(analyzer=self.analyzer.tokens, sublinear_tf=True)
        self._max_weight = 0.0
        self.current_matrix = self.vectorizer.fit_transform([c.text for c in self.current])
        self.superseded_matrix = (
            self.vectorizer.transform([c.text for c in self.superseded]) if self.superseded else None
        )
        self._max_weight = float(self.vectorizer.idf_.max())
        self._current_terms = [set(self.analyzer.tokens(c.text)) for c in self.current]
        self._superseded_terms = [set(self.analyzer.tokens(c.text)) for c in self.superseded]
        # Every word that occurs in ANY supplied document, including superseded revisions.
        self._known_terms = set(self.vectorizer.vocabulary_).union(*self._current_terms, *self._superseded_terms)

    def _weight(self, term: str) -> float:
        """Rarity of a word in the documents. A word found nowhere in them (e.g. 'pump') counts as the rarest."""
        position = self.vectorizer.vocabulary_.get(term)
        return float(self.vectorizer.idf_[position]) if position is not None else self._max_weight

    def _coverage(self, query_terms: set[str], chunk_terms: set[str]) -> float:
        """Share of the question's words found in a chunk, weighted by rarity.

        Plain counting let common words ("part", "number") hide a missing distinctive word ("pump"): the chunk
        looked like it covered half the question while missing the one word the question was really about.
        """
        total = sum(self._weight(t) for t in query_terms)
        return sum(self._weight(t) for t in query_terms & chunk_terms) / total if total else 0.0

    def search(self, question: str, top_k: int = config.TOP_K) -> SearchResult:
        query_terms = self.analyzer.tokens(question)
        term_set = set(query_terms)
        query_vector = self.vectorizer.transform([question])

        scores = (self.current_matrix @ query_vector.T).toarray().ravel()
        order = scores.argsort()[::-1][:top_k]
        current_hits = [Hit(self.current[i], float(scores[i])) for i in order]

        top_score = current_hits[0].score if current_hits else 0.0
        # Coverage = best share of the question's words found in any of the 3 best chunks. (Using only the
        # single best chunk wrongly blocked questions where a generic chunk narrowly outscored the right one.)
        coverage = max((self._coverage(term_set, self._current_terms[i]) for i in order[:3]), default=0.0)

        superseded_hits, older_versions = [], []
        if self.superseded_matrix is not None:
            top_docs = {h.chunk.doc_no for h in current_hits[:3]}
            old_scores = (self.superseded_matrix @ query_vector.T).toarray().ravel()
            for i in old_scores.argsort()[::-1][:4]:
                score, chunk = float(old_scores[i]), self.superseded[i]
                if score < config.MIN_TOP_SCORE:
                    continue
                strict = self._coverage(term_set, self._superseded_terms[i]) >= config.MIN_COVERAGE
                related = chunk.doc_no in top_docs and score >= 0.5 * top_score
                if strict:
                    superseded_hits.append(Hit(chunk, score))
                if strict or related:
                    older_versions.append(Hit(chunk, score))

        # Vague = fewer than two meaningful words and no code such as AL-104 ("What is the tolerance?").
        has_code = any(re.search(r"[a-z]", t) and re.search(r"\d", t) for t in query_terms)
        is_vague = len(term_set) < 2 and not has_code

        unknown = sorted(t for t in term_set if t not in self._known_terms)
        return SearchResult(current_hits, superseded_hits, older_versions, top_score, coverage, query_terms, is_vague,
                            unknown)

    @staticmethod
    def passes_gate(result: SearchResult) -> bool:
        if result.top_score < config.MIN_TOP_SCORE or result.coverage < config.MIN_COVERAGE:
            return False
        # Evidence must contain the question's distinctive words: an unknown word plus weak coverage = not found.
        return not (result.unknown_terms and result.coverage < config.UNKNOWN_TERM_MIN_COVERAGE)
