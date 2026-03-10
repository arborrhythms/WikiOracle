#!/usr/bin/env python3
"""
parse.py — English sentence → XML parse tree (5DG grammar)

Converts a plain English sentence into an XML tree following the operator
inventory defined in Grammar.md.  The pipeline is:

    tokenize  →  POS-tag  →  build CFG  →  Earley parse  →  emit XML

Two-pass parsing strategy:
    Pass 1 — strict: each word gets one category from NLTK's POS tagger.
    Pass 2 — broad:  on failure, WordNet synset lookup adds alternative
             categories, and the parser retries.

If both passes fail, every word is emitted as a <token word="..."/> leaf.
This preserves the surface string for downstream consumers while signalling
that the structural parse was unsuccessful.

Usage:
    python bin/parse.py "The quick brown fox jumps over the lazy dog."
"""

import sys
from pathlib import Path

import nltk
from nltk import pos_tag
from nltk.tokenize import word_tokenize
from nltk.grammar import CFG
from nltk.parse.earleychart import EarleyChartParser
from nltk.tree import Tree

# Ensure required NLTK data is available (silent no-ops if already present)
for _res in ("tokenizers/punkt_tab", "taggers/averaged_perceptron_tagger_eng",
             "corpora/wordnet"):
    try:
        nltk.data.find(_res)
    except LookupError:
        nltk.download(_res.split("/")[-1], quiet=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PUNCTUATION = set(".,;:?!\"'()-—–")

# ---------------------------------------------------------------------------
# Grammar loading — derive all word lists from grammar.cfg
# ---------------------------------------------------------------------------

_GRAMMAR_DIR = Path(__file__).resolve().parent.parent / "data"
_BASE_GRAMMAR = (_GRAMMAR_DIR / "grammar.cfg").read_text()
_BASE_CFG = CFG.fromstring(_BASE_GRAMMAR)

# Build function-word lookup from grammar's lexical rules.
# Maps lowercase word → terminal name, e.g. {"is": "IS", "over": "P", ...}.
_FUNC_WORDS = {}
_GRAMMAR_LEXICAL = set()  # (terminal_name, word) pairs already in grammar
for _prod in _BASE_CFG.productions():
    if _prod.is_lexical():
        _w = _prod.rhs()[0]
        _nt = str(_prod.lhs())
        _FUNC_WORDS[_w] = _nt
        _GRAMMAR_LEXICAL.add((_nt, _w))

# Coordination words — used by _select_tree to prefer clause-level parses.
_COORD_WORDS = {w for (nt, w) in _GRAMMAR_LEXICAL if nt in ("AND", "OR")}

# ---------------------------------------------------------------------------
# POS mapping: Penn Treebank tag → grammar terminal
# ---------------------------------------------------------------------------

def ptb_to_grammar(word, tag):
    """Map a (word, PTB-tag) pair to a list of grammar terminal names.

    Function words are identified by the grammar's lexical rules (grammar.cfg).
    Content words are classified by their POS tag.
    """
    low = word.lower()

    # Function words — lookup in grammar-derived table
    if low in _FUNC_WORDS:
        return [_FUNC_WORDS[low]]

    # Contraction fragments from NLTK tokenization
    # "won't" → ["wo", "n't"], "can't" → ["ca", "n't"]
    if low in ("wo", "ca"):
        return ["ADV"]

    # Punctuation
    if tag in (".", ",", ":", "``", "''", "-LRB-", "-RRB-") or word in PUNCTUATION:
        return ["PUNCT"]

    # Nouns
    if tag in ("NN", "NNS", "NNP", "NNPS", "PRP", "PRP$", "CD", "WP", "EX"):
        return ["N"]

    # Adjectives
    if tag in ("JJ", "JJR", "JJS"):
        return ["ADJ"]

    # Verbs
    if tag in ("VB", "VBD", "VBG", "VBN", "VBP", "VBZ"):
        return ["V"]

    # Adverbs
    if tag in ("RB", "RBR", "RBS", "WRB"):
        return ["ADV"]

    # Determiners
    if tag in ("DT", "PDT", "WDT"):
        return ["DET"]

    # Prepositions not in grammar → adjective fallback
    if tag in ("IN", "TO", "RP"):
        return ["ADJ"]

    # Coordination not in grammar
    if tag == "CC":
        return ["OR"]

    # Modal auxiliaries → adverb (modality via MP)
    if tag == "MD":
        return ["ADV"]

    # Possessive ending, foreign words, etc. → adjective fallback
    if tag in ("POS", "FW"):
        return ["ADJ"]

    # Unknown → noun (least committal)
    return ["N"]


def wordnet_categories(word):
    """Get all possible grammar terminal names for a word using WordNet.

    Used as fallback when strict POS-based parsing fails.
    Function words get their grammar terminal; content words use WordNet
    synsets to determine all plausible open-class terminals.
    """
    from nltk.corpus import wordnet as wn

    low = word.lower()
    cats = []

    # Function word from grammar
    if low in _FUNC_WORDS:
        cats.append(_FUNC_WORDS[low])

    # Modal auxiliaries (including contraction fragments) → ADV only
    if low in ("can", "could", "will", "would", "shall", "should",
               "may", "might", "must", "wo", "ca"):
        if "ADV" not in cats:
            cats.append("ADV")
        return cats

    # Pronouns → N
    if low in ("i", "me", "you", "he", "him", "she", "it",
               "we", "us", "they", "them", "what", "who", "whom"):
        if "N" not in cats:
            cats.append("N")
        return cats

    # Content words: WordNet lookup
    synsets = wn.synsets(low)

    if not synsets:
        if not cats:
            return ["N", "V", "ADJ"]
        return cats

    wn_pos = {s.pos() for s in synsets}
    if "n" in wn_pos and "N" not in cats:
        cats.append("N")
    if "v" in wn_pos and "V" not in cats:
        cats.append("V")
    if ("a" in wn_pos or "s" in wn_pos) and "ADJ" not in cats:
        cats.append("ADJ")
    if "r" in wn_pos and "ADV" not in cats:
        cats.append("ADV")

    return cats if cats else ["N"]


# ---------------------------------------------------------------------------
# CFG builder
# ---------------------------------------------------------------------------

def build_grammar(tagged_tokens):
    """Build an NLTK CFG from external grammar + dynamic content-word rules.

    tagged_tokens is a list of (word, [terminal1, terminal2, ...]) pairs.

    Function words match the enumerated lexical rules already in grammar.cfg.
    Content words (N, V, ADJ, ADV) and case-variants of function words get
    dynamic terminal rules added here.
    """
    from nltk.grammar import Nonterminal, Production

    productions = list(_BASE_CFG.productions())

    seen = set()
    for word, cats in tagged_tokens:
        for cat in cats:
            key = (cat, word)
            if key not in _GRAMMAR_LEXICAL and key not in seen:
                seen.add(key)
                productions.append(Production(Nonterminal(cat), [word]))

    return CFG(Nonterminal("S"), productions)


# ---------------------------------------------------------------------------
# Tree → XML transformer
# ---------------------------------------------------------------------------

def _definitive_surface(op_tree):
    """Extract surface word and optional negation from DEF/HAS nonterminal.

    DEF → IS             → ('is', None)    — definitive identity
    DEF → IS NOT         → ('is', "n't")   — negated definitive
    HAS → POSSESS        → ('has', None)   — definitive possession
    HAS → POSSESS NOT    → ('has', 'not')  — negated definitive possession
    """
    ch = list(op_tree)
    base = ch[0]
    surface = base[0] if isinstance(base, Tree) else base
    if len(ch) > 1:
        neg = ch[1]
        neg_word = neg[0] if isinstance(neg, Tree) else neg
        return surface, neg_word
    return surface, None


def _not_tag(surface_word):
    """Return 'non' XML tag if surface is 'non', else 'not'."""
    return "non" if surface_word.lower() == "non" else "not"


def _emit_definitive(pad, indent, op_tag, op_tree, subject, predicate):
    """Emit XML for a definitive construction (is/has).

    When the DEF/HAS nonterminal contains negation (DEF → IS NOT),
    the negation wraps the predicate:

        <is word="is">               <is word="is">
          <n word="water"/>    vs      <n word="water"/>
          <adj word="wet"/>            <not word="n't">
        </is>                            <adj word="wet"/>
                                       </not>
                                     </is>
    """
    surface, neg = _definitive_surface(op_tree)
    lines = [f'{pad}<{op_tag} word="{surface}">']
    lines.append(tree_to_xml(subject, indent + 1))
    if neg:
        tag = _not_tag(neg)
        inner_pad = "  " * (indent + 1)
        lines.append(f'{inner_pad}<{tag} word="{neg}">')
        lines.append(tree_to_xml(predicate, indent + 2))
        lines.append(f'{inner_pad}</{tag}>')
    else:
        lines.append(tree_to_xml(predicate, indent + 1))
    lines.append(f"{pad}</{op_tag}>")
    return "\n".join(lines)


def tree_to_xml(tree, indent=0):
    """Convert an NLTK parse tree into indented XML following Grammar.md.

    Each production rule maps to a specific operator:
        union        — rank-lifting composition (predication, prepositional, modal)
        intersection — rank-dropping composition (adjective/adverb narrowing)
        conjunction  — accumulative coordination (and)
        disjunction  — alternative coordination (or)
        is / has     — definitive identity / possession (via _emit_definitive)
        not / non    — negation / privation
        prep         — preposition relocating attention head

    Terminal nonterminals (N, ADJ, V, …) emit self-closing XML leaves.
    Operator-word terminals (IS, POSSESS, NOT, AND, OR) return None
    because their surface words are emitted by the parent operator element.
    """
    pad = "  " * indent

    # Raw string leaves are handled by their parent nonterminal, not here.
    if isinstance(tree, str):
        return None

    label = tree.label()
    children = list(tree)

    # --- Terminal nonterminals (single leaf child) ---
    if len(children) == 1 and isinstance(children[0], str):
        word = children[0]
        tag_map = {
            "N": "n", "ADJ": "adj", "V": "v", "ADV": "adv",
            "DET": "det", "DEG": "deg", "P": "p", "PUNCT": "punct",
        }
        # Operator-word terminals (handled by parent operator)
        if label in ("IS", "POSSESS", "NOT", "AND", "OR"):
            return None
        xml_tag = tag_map.get(label, "n")
        return f'{pad}<{xml_tag} word="{word}"/>'

    # --- Identify the production rule pattern ---
    child_labels = []
    for c in children:
        if isinstance(c, Tree):
            child_labels.append(c.label())
        else:
            child_labels.append(c)

    # --- S rules ---
    if label == "S":
        if child_labels == ["NP"]:
            return tree_to_xml(children[0], indent)

        if child_labels == ["NP", "VP"]:
            # Predication: VP applied to subject (predicate first by convention)
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[1], indent + 1))  # VP (predicate)
            lines.append(tree_to_xml(children[0], indent + 1))  # NP (subject)
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["MP", "S"]:
            # Modal augmentation: adverb scoping over the entire sentence
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["PP", "S"]:
            # Pre-sentential PP adjunct: "In my opinion this is wrong"
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        # Definitive rules — DEF/HAS nonterminals handle negation internally
        if child_labels == ["NP", "DEF", "NP"]:
            return _emit_definitive(pad, indent, "is", children[1], children[0], children[2])

        if child_labels == ["NP", "DEF", "AP"]:
            return _emit_definitive(pad, indent, "is", children[1], children[0], children[2])

        if child_labels == ["NP", "HAS", "NP"]:
            return _emit_definitive(pad, indent, "has", children[1], children[0], children[2])

        if child_labels == ["NOT", "S"]:
            # Sentence negation or privation: "not S" / "non S"
            surface = children[0][0] if isinstance(children[0], Tree) else children[0]
            tag = _not_tag(surface)
            lines = [f'{pad}<{tag} word="{surface}">']
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</{tag}>")
            return "\n".join(lines)

        if child_labels == ["S", "AND", "S"]:
            # Clause coordination: "the dog barks and the cat meows"
            word = children[1][0] if isinstance(children[1], Tree) else children[1]
            lines = [f'{pad}<conjunction word="{word}">']
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[2], indent + 1))
            lines.append(f"{pad}</conjunction>")
            return "\n".join(lines)

        if child_labels == ["S", "OR", "S"]:
            # Clause disjunction: "you stay or you go"
            word = children[1][0] if isinstance(children[1], Tree) else children[1]
            lines = [f'{pad}<disjunction word="{word}">']
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[2], indent + 1))
            lines.append(f"{pad}</disjunction>")
            return "\n".join(lines)

        if child_labels == ["DEF", "NP", "AP"]:
            # Definitive question (inverted): "Is water wet?" / "Isn't water wet?"
            return _emit_definitive(pad, indent, "is", children[0], children[1], children[2])

        if child_labels == ["DEF", "NP", "NP"]:
            # Definitive question with NP predicate (inverted): "Is Paris the capital?"
            return _emit_definitive(pad, indent, "is", children[0], children[1], children[2])

        if child_labels == ["V", "NP", "VP"]:
            # Auxiliary question (inverted): "Does the fox jump?"
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[0], indent + 1))  # auxiliary verb
            inner = [f"{'  ' * (indent + 1)}<union>"]
            inner.append(tree_to_xml(children[2], indent + 2))  # VP (predicate)
            inner.append(tree_to_xml(children[1], indent + 2))  # NP (subject)
            inner.append(f"{'  ' * (indent + 1)}</union>")
            lines.append("\n".join(inner))
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

    # --- NP rules ---
    if label == "NP":
        if child_labels == ["N"]:
            # Bare noun: pass through to leaf
            return tree_to_xml(children[0], indent)

        if child_labels == ["AP", "NP"]:
            # Modifier narrowing: "the quick brown fox"
            lines = [f"{pad}<intersection>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</intersection>")
            return "\n".join(lines)

        if child_labels == ["NP", "PP"]:
            # NP modified by prepositional phrase: "the dog on the hill"
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[1], indent + 1))  # PP
            lines.append(tree_to_xml(children[0], indent + 1))  # NP
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["NP", "AND", "NP"]:
            # Accumulative NP coordination: "dogs and cats"
            word = children[1][0] if isinstance(children[1], Tree) else children[1]
            lines = [f'{pad}<conjunction word="and">']
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[2], indent + 1))
            lines.append(f"{pad}</conjunction>")
            return "\n".join(lines)

        if child_labels == ["NP", "OR", "NP"]:
            # Alternative NP coordination: "dogs or cats"
            word = children[1][0] if isinstance(children[1], Tree) else children[1]
            lines = [f'{pad}<disjunction word="or">']
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[2], indent + 1))
            lines.append(f"{pad}</disjunction>")
            return "\n".join(lines)

    # --- VP rules ---
    if label == "VP":
        if child_labels == ["V"]:
            # Intransitive: pass through to leaf
            return tree_to_xml(children[0], indent)

        if child_labels == ["ADV", "VP"]:
            # Pre-verbal adverb narrowing: "quickly runs"
            lines = [f"{pad}<intersection>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</intersection>")
            return "\n".join(lines)

        if child_labels == ["MP", "VP"]:
            # Modal augmentation at VP level
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["ADJ", "VP"]:
            # Verb modifier narrowing (non-spatial prepositions, etc.)
            lines = [f"{pad}<intersection>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</intersection>")
            return "\n".join(lines)

        if child_labels == ["V", "NP"]:
            # Transitive verb + direct object: "contains hydrogen"
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[0], indent + 1))  # V (predicate)
            lines.append(tree_to_xml(children[1], indent + 1))  # NP (object)
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["V", "PP"]:
            # Verb + PP complement: "jumps over the dog"
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["V", "S"]:
            # Verb + clause complement: "I think [the fox jumps]"
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["V", "MP"]:
            # Post-verbal adverb: "runs quickly"
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["DEF", "VP"]:
            # Passive/progressive auxiliary: "is defined", "is running"
            # The copula is absorbed into the VP as a verbal element.
            surface, neg = _definitive_surface(children[0])
            lines = [f"{pad}<union>"]
            lines.append(f'{"  " * (indent + 1)}<v word="{surface}"/>')
            if neg:
                tag = _not_tag(neg)
                inner_pad = "  " * (indent + 1)
                lines.append(f'{inner_pad}<{tag} word="{neg}">')
                lines.append(tree_to_xml(children[1], indent + 2))
                lines.append(f'{inner_pad}</{tag}>')
            else:
                lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["VP", "PP"]:
            # Post-verbal PP modification: "ran to the store"
            lines = [f"{pad}<union>"]
            lines.append(tree_to_xml(children[1], indent + 1))  # PP (modifier)
            lines.append(tree_to_xml(children[0], indent + 1))  # VP (head)
            lines.append(f"{pad}</union>")
            return "\n".join(lines)

        if child_labels == ["NOT", "VP"]:
            # VP-internal negation: "would not recommend"
            surface = children[0][0] if isinstance(children[0], Tree) else children[0]
            tag = _not_tag(surface)
            lines = [f'{pad}<{tag} word="{surface}">']
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</{tag}>")
            return "\n".join(lines)

    # --- AP rules ---
    if label == "AP":
        if child_labels == ["ADJ"]:
            # Bare adjective: pass through to leaf
            return tree_to_xml(children[0], indent)
        if child_labels == ["DET"]:
            # Bare determiner: pass through to leaf
            return tree_to_xml(children[0], indent)
        if child_labels == ["ADJ", "AP"]:
            # Adjective narrowing: "quick brown" → intersect(quick, brown)
            lines = [f"{pad}<intersection>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</intersection>")
            return "\n".join(lines)

        if child_labels == ["DEG", "AP"]:
            # Degree hedge modifying adjective (e.g. "very hot", "quite tall")
            lines = [f"{pad}<intersection>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</intersection>")
            return "\n".join(lines)

    # --- MP rules ---
    if label == "MP":
        if child_labels == ["ADV"]:
            # Bare adverb: pass through to leaf
            return tree_to_xml(children[0], indent)
        if child_labels == ["ADV", "MP"]:
            # Adverb narrowing: "very probably" → intersect(very, probably)
            lines = [f"{pad}<intersection>"]
            lines.append(tree_to_xml(children[0], indent + 1))
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</intersection>")
            return "\n".join(lines)

    # --- PP rules ---
    if label == "PP":
        if child_labels == ["P", "NP"]:
            prep_word = children[0][0] if isinstance(children[0], Tree) else children[0]
            lines = [f'{pad}<prep word="{prep_word}">']
            lines.append(tree_to_xml(children[1], indent + 1))
            lines.append(f"{pad}</prep>")
            return "\n".join(lines)

    # Fallback: unrecognised production — emit children as-is.
    # This should not normally be reached; it guards against grammar
    # extensions that add new rules without updating tree_to_xml().
    parts = []
    for c in children:
        if isinstance(c, Tree):
            parts.append(tree_to_xml(c, indent))
        else:
            parts.append(f'{pad}<n word="{c}"/>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main parse pipeline
# ---------------------------------------------------------------------------

def has_clause_coord(tree):
    """Check if tree uses clause coordination (S → S AND/OR S).

    Used by _select_tree() to prefer parses that capture clause-level
    coordination over those that bury coordinators inside NPs or VPs.
    """
    if isinstance(tree, str):
        return False
    label = tree.label()
    children = list(tree)
    child_labels = [c.label() if isinstance(c, Tree) else c for c in children]
    if label == "S" and child_labels.count("S") >= 2:
        return True
    return any(has_clause_coord(c) for c in children if isinstance(c, Tree))


def fix_noun_modifiers(grammar_tokens):
    """Allow noun-as-modifier when two nouns are adjacent.

    English frequently uses nouns as modifiers ("chicken soup", "car door").
    The POS tagger labels both words as nouns, but the grammar needs the
    first one to also be available as an adjective so NP → AP NP can fire.
    This pass adds "ADJ" as an alternative terminal for any noun that
    immediately precedes another noun.
    """
    result = list(grammar_tokens)
    for i in range(len(result) - 1):
        word_i, cats_i = result[i]
        _, cats_next = result[i + 1]
        if "N" in cats_i and "N" in cats_next and "ADJ" not in cats_i:
            result[i] = (word_i, cats_i + ["ADJ"])
    return result


def _try_parse(grammar_tokens, max_trees=50):
    """Attempt to parse grammar_tokens, returning list of NLTK Trees (may be empty).

    grammar_tokens: list of (word, [terminal1, ...]) pairs.
    max_trees: cap on how many parses to enumerate.

    The parser receives actual words.  Function words match lexical rules
    in grammar.cfg; content words match dynamic rules added by build_grammar.
    """
    grammar = build_grammar(grammar_tokens)
    parser = EarleyChartParser(grammar)
    chart_tokens = [word for word, _ in grammar_tokens]

    trees = []
    for i, t in enumerate(parser.parse(chart_tokens)):
        trees.append(t)
        if i >= max_trees - 1:
            break
    return trees


def _select_tree(trees, grammar_tokens):
    """Pick the best tree from a list of parses.

    Prefers clause-coordination parses when coordination tokens are present.
    """
    tree = trees[0]
    has_coord = any(w.lower() in _COORD_WORDS for w, _ in grammar_tokens)
    if has_coord and not has_clause_coord(tree):
        for candidate in trees[1:]:
            if has_clause_coord(candidate):
                tree = candidate
                break
    return tree


def parse(sentence):
    """Tokenize, POS-tag, parse, and emit XML for a sentence.

    Two-pass strategy:
      Pass 1 — trust NLTK's POS tagger (strict, one category per word).
      Pass 2 — on failure, fall back to WordNet synset lookup for broader
               category alternatives, and retry.
    """
    # Tokenize
    tokens = word_tokenize(sentence)
    if not tokens:
        return ""

    # POS tag
    tagged = pos_tag(tokens)

    # Separate punctuation from content words
    content_tagged = []
    punct_tokens = []
    for word, tag in tagged:
        cats = ptb_to_grammar(word, tag)
        if cats == ["PUNCT"]:
            punct_tokens.append(word)
        else:
            content_tagged.append((word, tag, cats))

    if not content_tagged:
        return "\n".join(f'<punct word="{w}"/>' for w in punct_tokens)

    # --- Pass 1: strict POS categories ---
    grammar_tokens = [(word, cats) for word, tag, cats in content_tagged]
    grammar_tokens = fix_noun_modifiers(grammar_tokens)

    trees = _try_parse(grammar_tokens)

    # --- Pass 2: WordNet fallback (broader categories) ---
    if not trees:
        wn_tokens = []
        for word, tag, strict_cats in content_tagged:
            broad_cats = wordnet_categories(word)
            # Merge: start with strict, add any WordNet categories not yet present
            merged = list(strict_cats)
            for c in broad_cats:
                if c not in merged:
                    merged.append(c)
            wn_tokens.append((word, merged))

        wn_tokens = fix_noun_modifiers(wn_tokens)
        trees = _try_parse(wn_tokens)
        grammar_tokens = wn_tokens  # for _select_tree coord detection

    if not trees:
        # Graceful degradation: emit <token> leaves for unparsed words
        print(f"No parse found (token fallback): {sentence}", file=sys.stderr)
        parts = []
        for word, cats in grammar_tokens:
            parts.append(f'<token word="{word}"/>')
        for p in punct_tokens:
            parts.append(f'<punct word="{p}"/>')
        return "\n".join(parts)

    # Select best tree
    tree = _select_tree(trees, grammar_tokens)

    # Convert to XML
    xml = tree_to_xml(tree)

    # Append punctuation
    for p in punct_tokens:
        xml += f'\n<punct word="{p}"/>'

    return xml


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI entry point: parse each argument as a sentence and print XML."""
    if len(sys.argv) < 2:
        print("Usage: python parse.py \"sentence\"", file=sys.stderr)
        sys.exit(1)

    sentence = " ".join(sys.argv[1:])
    result = parse(sentence)
    print(result)


if __name__ == "__main__":
    main()
