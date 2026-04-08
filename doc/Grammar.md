# Grammar

This grammar renders English as XML with a small fixed inventory. It favors three things over full formal rigor:

- every surface token stays visible
- narrowing and broadening are explicit
- operator application is marked explicitly

Limits:

- This is a compact parse grammar, not a complete formal semantics.
- Some surface distinctions are intentionally collapsed.
- Witness leaves keep the sentence recoverable even when the structural parse is imperfect.
- The price of that recoverability is that some nodes contain surface witnesses in addition to their semantic operands.

## Inventory

### Operators

- `<union>`: binary rank-lifting composition (direct sum $\oplus$; joins independent feature spaces)
- `<intersection>`: binary rank-dropping composition (Hadamard masking $\odot$; narrows or selects within a space)
- `<conjunction word="and">`: binary accumulative coordination (surface word on attribute)
- `<disjunction word="or">`: binary alternative coordination (surface word on attribute)
- `<not word="...">`: unary negation (surface word: `not`, `n't`)
- `<non word="...">`: unary privation (surface word: `non`). Shares the NOT nonterminal with `<not>`; the XML tag is chosen by surface word
- `<prep word="...">`: unary prepositional relation (all prepositions — spatial such as `over`, `under`, `in`, `out` and non-spatial such as `of`, `to`, `for`, `with` — live in perceptual space and relocate the attention head without changing dimensionality)
- `<is word="...">`: identity or definition (surface word on attribute)
- `<has word="...">`: possession or parthood (surface word on attribute)

### Leaves

- `<n word="..."/>`: noun
- `<adj word="..."/>`: adjective (noun modifier or verb modifier)
- `<v word="..."/>`: verb
- `<adv word="..."/>`: adverb
- `<det word="..."/>`: determiner or article
- `<deg word="..."/>`: degree modifier or hedge (fuzzy scalar)
- `<punct word="..."/>`: punctuation
- `<token word="..."/>`: unparsed word (fallback when the parser cannot find a valid parse tree; preserves surface structure but signals failure)
- `<space word=" "/>`: whitespace (preserves token boundaries for lossless surface reconstruction)

### Nonterminals

These are not XML elements but shorthand for common subtree patterns:

- **S** (sentence)
- **NP** (noun phrase): `[AP n]` — modifier phrase followed by a noun head
- **VP** (verb phrase): `[(adv|MP|adj)* v]` — optional adverbs, modal phrases, or verb modifiers followed by a verb head
- **AP** (adjectival phrase): `[(adj|det|deg)* (adj|det)]` — adjectives, determiners, and degree modifiers; handles all narrowing modifiers
- **MP** (modal phrase): `[adv* adv]` — zero or more adverb modifiers followed by an adverb head
- **PP** (prepositional phrase)
- **IS** (definitive operator): `[copula NOT?]` — definitive surface word, optionally followed by negation
- **HAS** (possession operator): `[possess NOT?]` — possession surface word, optionally followed by negation
- **NOT** (negation): covers both `not`/`n't` (→ `<not>`) and `non` (→ `<non>`)

### Production Rules

**Sentence:**

| Rule          | Operator          | Meaning                                             |
| ------------- | ----------------- | --------------------------------------------------- |
| S → NP        | —                 | bare noun phrase as sentence                        |
| S → NP VP     | `<union>`         | predication: VP applied to subject                  |
| S → MP S      | `<union>`         | modal augmentation                                  |
| S → PP S      | `<union>`         | pre-sentential PP adjunct                           |
| S → NP IS NP  | `<is>`            | is of definition                                    |
| S → NP IS AP  | `<is>`            | is of predication                                   |
| S → NP HAS NP | `<has>`           | parthood                                            |
| S → NOT S     | `<not>` / `<non>` | negation, affirming and non-affirming               |
| S → S `and` S | `<conjunction>`   | clause coordination                                 |
| S → S `or` S  | `<disjunction>`   | clause disjunction                                  |
| S → IS NP AP  | `<is>`            | question of predication (inverted)                  |
| S → IS NP NP  | `<is>`            | question of definition with NP predicate (inverted) |
| S → v NP VP   | `<union>`         | auxiliary question (inverted)                       |

**Noun Phrase:**

| Rule             | Operator         | Meaning                             |
| ---------------- | ---------------- | ----------------------------------- |
| NP → n           | —                | bare noun                           |
| NP → AP NP       | `<intersection>` | modifier narrowing                  |
| NP → NP PP       | `<union>`        | NP modified by prepositional phrase |
| NP → NP `and` NP | `<conjunction>`  | accumulative coordination           |
| NP → NP `or` NP  | `<disjunction>`  | alternative coordination            |

**Verb Phrase:**

| Rule          | Operator         | Meaning                         |
| ------------- | ---------------- | ------------------------------- |
| VP → v        | —                | intransitive                    |
| VP → v NP     | `<union>`        | transitive verb + direct object |
| VP → adv VP.  | `<intersection>` | adverb narrowing                |
| VP → MP VP    | `<union>`        | modal augmentation              |
| VP → adj VP.  | `<intersection>` | verb modifier narrowing         |
| VP → v PP     | `<union>`        | verb + PP complement            |
| VP → v S      | `<union>`        | verb + clause complement        |
| VP → v MP     | `<union>`        | post-verbal adverb              |
| VP → VP PP    | `<union>`        | post-verbal PP modification     |
| VP → IS VP    | `<union>`        | passive/progressive auxiliary   |
| VP → `not` VP | `<not>`          | VP-internal negation            |

**Adjectival Phrase:**

| Rule        | Operator         | Meaning             |
| ----------- | ---------------- | ------------------- |
| AP → adj    | —                | bare adjective      |
| AP → det    | —                | bare determiner     |
| AP → adj AP | `<intersection>` | adjective narrowing |
| AP → deg AP | `<intersection>` | degree hedging      |

**Modal Phrase:**

| Rule        | Operator         | Meaning          |
| ----------- | ---------------- | ---------------- |
| MP → adv    | —                | bare adverb      |
| MP → adv MP | `<intersection>` | adverb narrowing |

**Prepositional Phrase:**

| Rule      | Operator | Meaning                  |
| --------- | -------- | ------------------------ |
| PP → p NP | `<prep>` | preposition + complement |

**Definitive:**

| Rule          | Meaning                                         |
| ------------- | ----------------------------------------------- |
| IS → `is`     | bare definitive (`is`, `are`, `was`, `were`, …) |
| IS → `is` NOT | negated definitive (`isn't`, `is not`, …)       |

**Possession:**

| Rule            | Meaning                                     |
| --------------- | ------------------------------------------- |
| HAS → `has`     | bare possession (`has`, `have`, `had`, …)   |
| HAS → `has` NOT | negated possession (`hasn't`, `has not`, …) |

**Negation:**

| Rule        | XML tag | Meaning                 |
| ----------- | ------- | ----------------------- |
| NOT → `not` | `<not>` | negation (`not`, `n't`) |
| NOT → `non` | `<non>` | privation (`non`)       |

## Surface Preservation Rule

Every surface token should appear somewhere as a leaf. The operators carry the composition; the leaves preserve the visible words.

Semantic arity:

- `union`, `intersection`, `conjunction`, `disjunction`, `is`, `has`: binary
- `not`, `non`, `prep`: unary

To preserve the surface string, operators that carry a surface word use the `word` attribute (e.g. `<conjunction word="and">`, `<is word="is">`, `<prep word="over">`). Terminal punctuation should usually sit outside the clause operator as its own leaf.

## Definitive Before Predication Rule

Before mapping a clause to an ordinary verb phrase, check whether it is definitional, classificatory, part-whole, or about language itself.

Use `<is>` first when:

- the sentence equates one thing with another
- the sentence defines a term
- the sentence says one thing is a kind, member, or part of another
- the sentence attributes a property by means of a definitive form rather than an event verb
- the sentence is about a word, label, or linguistic expression

Examples:

- `water is h2o` -> prefer `<is>`
- `a robin is a bird` -> prefer `<is>`
- `water is wet` -> prefer `<is>`, not an ordinary eventive `<v>`

Preserve the surface copula on the operator itself, for example `<is word="is">...</is>`, but do not let that force the whole clause into the ordinary `union + v` pattern.

## Main Example

Surface sentence:

`The quick brown fox probably jumps over the lazy dog and the sleepy cat.`

Parse:

```xml
<union>
  <adv word="probably"/>
  <union>
    <union>
      <v word="jumps"/>
      <prep word="over">
        <conjunction word="and">
          <intersection>
            <det word="the"/>
            <intersection>
              <adj word="lazy"/>
              <n word="dog"/>
            </intersection>
          </intersection>
          <intersection>
            <det word="the"/>
            <intersection>
              <adj word="sleepy"/>
              <n word="cat"/>
            </intersection>
          </intersection>
        </conjunction>
      </prep>
    </union>
    <intersection>
      <det word="the"/>
      <intersection>
        <adj word="quick"/>
        <intersection>
          <adj word="brown"/>
          <n word="fox"/>
        </intersection>
      </intersection>
    </intersection>
  </union>
</union>
<punct word="."/>
```

Reading:

```text
probably((jumps(over(the(lazy(dog)) and the(sleepy(cat)))))(the(quick(brown(fox)))))
```

## What The Operators Mean

- `<union>`: use when one expression takes another as an argument and creates a higher-dimensional construct (direct sum, rank lifting).
  Example: `NP VP` (predication), `MP S` (modal augmentation), `v NP` (transitive).
- `<intersection>`: use when composition narrows, selects, or restricts within a space (Hadamard masking, rank dropping). Covers adjective narrowing, determiner selection, and any other narrowing.
  Example: `brown fox`, `the fox`, `quick brown fox`.
- `<conjunction word="and">`: use when coordinating by accumulation — both operands are gathered together. The surface word goes on the attribute.
  Example: `<conjunction word="and">dogs, cats</conjunction>`.
- `<disjunction word="or">`: use when coordinating by presenting alternatives — one or the other. The surface word goes on the attribute.
  Example: `<disjunction word="or">dogs, cats</disjunction>`.
- `<prep word="...">`: use when any preposition (spatial or non-spatial) establishes a relation. All prepositions live in perceptual space and relocate the attention head without changing dimensionality. The preposition goes on the operator attribute; the single child is the complement.
  Example: `<prep word="over">the dog</prep>`, `<prep word="of">France</prep>`.
- `<not word="not">`: ordinary sentence or predicate negation. The surface word goes on the attribute.
  Example: `<not word="not">S</not>`.
- `<non word="non">`: lexical privation. The surface word goes on the attribute.
  Example: `<non word="non">human</non>`.
- `<is word="is">`: identity, equivalence, definition, or classification. The surface word goes on the attribute.
  Example: `<is word="is">water, h2o</is>`.
- `<has word="has">`: possession or parthood. The surface word goes on the attribute.
  Example: `<has word="has">the dog, a tail</has>`.

## Minimal Examples

Definition (`water is h2o`):

```xml
<is word="is">
  <n word="water"/>
  <adj word="h2o"/>
</is>
```

Classification (`a robin is a bird`):

```xml
<is word="is">
  <intersection>
    <det word="a"/>
    <n word="robin"/>
  </intersection>
  <intersection>
    <det word="a"/>
    <n word="bird"/>
  </intersection>
</is>
<punct word="."/>
```

Definitive predication (`water is wet`):

```xml
<is word="is">
  <n word="water"/>
  <adj word="wet"/>
</is>
<punct word="."/>
```

Passive (`a polygon is defined as a closed shape`):

```xml
<union>
  <union>
    <v word="is"/>
    <union>
      <v word="defined"/>
      <prep word="as">
        <intersection>
          <det word="a"/>
          <intersection>
            <adj word="closed"/>
            <n word="shape"/>
          </intersection>
        </intersection>
      </prep>
    </union>
  </union>
  <intersection>
    <det word="A"/>
    <n word="polygon"/>
  </intersection>
</union>
<punct word="."/>
```

Negation (`the fox does not jump`):

```xml
<union>
  <union>
    <v word="does"/>
    <not word="not">
      <v word="jump"/>
    </not>
  </union>
  <intersection>
    <det word="the"/>
    <n word="fox"/>
  </intersection>
</union>
<punct word="."/>
```

## Suggested Mappings Into This Inventory

| English item                                                                     | Default mapping                     | Notes                                                                         |
| -------------------------------------------------------------------------------- | ----------------------------------- | ----------------------------------------------------------------------------- |
| common noun, proper noun, pronoun, nominal numeral                               | `<n>`                               | `alice`, `she`, `three`                                                       |
| adjective, participle-as-modifier, ordinal, noun modifier                        | `<adj>`                             | `broken`, `first`, `chicken` in `chicken soup`                                |
| non-spatial preposition (`of`, `to`, `at`, `for`, `from`, `with`, `about`, `by`) | `<prep word="...">`                 | forms PP like spatial preps; learns characteristic transform through exposure |
| complementizer, remaining prepositions                                           | `<adj>`                             | verb modifiers: `that`, `as`                                                  |
| modal auxiliary                                                                  | `<adv>`                             | modality via MP: `must`, `should`, `can`, `will`                              |
| subordinating conjunction, `but`                                                 | `word` attribute on `<conjunction>` | clause joiners: `because`, `although`, `but`, `since`                         |
| main verb, auxiliary with real verbal force                                      | `<v>`                               | `runs`, `jumped`, `slept`                                                     |
| adverb, sentence adverb, modal adverb                                            | `<adv>`                             | `quickly`, `probably`, `maybe`                                                |
| degree modifier, hedge, scalar intensifier                                       | `<deg>`                             | `very`, `quite`, `somewhat`, `rather`, `extremely`                            |
| determiner, article                                                              | `<det>`                             | `the`, `a`, `this`, `every`                                                   |
| spatial preposition                                                              | `<prep word="...">`                 | `over`, `under`, `up`, `down`, `in`, `out`                                    |
| coordinator `and`                                                                | `word` attribute on `<conjunction>` | `<conjunction word="and">`                                                    |
| coordinator `or`                                                                 | `word` attribute on `<disjunction>` | `<disjunction word="or">`                                                     |
| punctuation                                                                      | `<punct>`                           | `. , ; : ? !`                                                                 |

Practical special cases:

- Determiners and articles appear as `det` under `intersection`.
- All prepositions (spatial and non-spatial) appear as the `word` attribute on `<prep>`, e.g. `<prep word="over">...</prep>`, `<prep word="of">...</prep>`. Both types live in perceptual space and form PPs via `PP → p NP`.
- Surface `and` is preserved as the `word` attribute on `conjunction`, e.g. `<conjunction word="and">...</conjunction>`.
- Surface `or` is preserved as the `word` attribute on `disjunction`, e.g. `<disjunction word="or">...</disjunction>`.
- Modal adverbs such as `probably` stay `adv` within an MP and take sentence scope via `S → MP S` (union). Manner adverbs such as `quickly` narrow the verb via `VP → adv VP` (intersection).
- Degree modifiers such as `very`, `quite`, `somewhat`, `rather` hedge an adjective and are mapped to `deg`; they narrow via `AP → deg AP` (intersection).
- Modal auxiliaries such as `must`, `should`, and `can` express modality and are mapped to `adv`; they modify the verb via `VP → MP VP` (union).
- Coordinating `but`, `yet`, `nor` are treated as conjunction (like `and`) for clause coordination via `S → S and S`.
- Subordinating conjunctions such as `because`, `since`, `although` are treated as conjunction for clause-level coordination via `S → S and S`.
- Verb-complement clauses such as "I think [the fox jumps]" use `VP → v S` (union); the embedded clause is a full sentence.
- Definitive forms such as `is`, `are`, `was`, `were`, `has`, and `have` should be tested against `<is>` or `<has>` before falling back to `<v>`.
- Negated definitives such as `isn't`, `hasn't` are handled by the IS and HAS nonterminals: `IS → is NOT`, `HAS → has NOT`. The negation scopes over the predicate: `<is word="is"><not word="n't">predicate</not></is>`.
- `NOT` covers both negation (`not`, `n't` → `<not>`) and privation (`non` → `<non>`). English does not disambiguate at the surface level, so both share a single nonterminal.
- Contraction fragments such as `wo` (from `won't`) and `ca` (from `can't`) are mapped to `<adv>` (modal) so they enter through MP.
- Post-verbal adverbs such as "runs quickly" use `VP → v MP` (union), symmetric with pre-verbal `VP → MP VP`.
- Terminal punctuation should usually be emitted outside the clause operator it closes.

## Short Parsing Procedure

1. Keep every surface token.
2. Map visible words to `n`, `adj`, `v`, `adv`, `det`, or `punct`.
3. Before using `<v>`, test whether the clause is better represented by `<is>`.
4. Build NPs from the head outward with `intersection`: NP = [AP n].
5. Build VPs similarly with `intersection`: VP = [adv* v].
6. Use `conjunction` for accumulative coordination (`and`).
7. Use `disjunction` for alternative coordination (`or`).
8. Use `union` whenever a word or phrase takes an argument and augments dimensionality.
9. Use `intersection` when a modifier or determiner narrows or selects within a space.
10. Use `prep` when any preposition (spatial or non-spatial) establishes a relation without changing dimensionality.
11. Use `is` for identity, definition, property attribution, classification, and parthood.
12. Use `not` for ordinary negation and `non` for lexical privation.
13. If uncertain, preserve the word as a `token`

## Mapping Syntax to Architecture

This section outlines the formal operations used to assemble and disassemble operations on Perceptual, Conceptual, and Symbolic spaces.

### Summary Table

| Process          | Operation             | Rank Effect    | Linguistic Analogy                 | Space                        |
| :--------------- | :-------------------- | :------------- | :--------------------------------- | :--------------------------- |
| **Prep**         | Relocation            | **Preserving** | Relocating over the bridge.        | Perceptual Space             |
| **Has**          | Composition           | **Preserving** | A dog having a tail.               | Perceptual Space             |
| **Union**        | Direct Sum ($\oplus$) | **Lifting**    | Building a sentence from words.    | Conceptual Space             |
| **Intersection** | Hadamard ($\odot$)    | **Dropping**   | Narrowing a noun by its adjective. | Conceptual Space             |
| **Conjunction**  | Accumulation          | **Preserving** | Gathering dogs and cats.           | Symbolic Space               |
| **Disjunction**  | Alternation           | **Preserving** | Choosing dogs or cats.             | Symbolic Space               |
| **Not**          | Negation              | **Preserving** | Negating a sentence.               | Conceptual or Symbolic Space |
| **Non**          | Privation             | **Dropping**   | Excluding a property.              | Conceptual or Symbolic Space |
| **Is**           | Identification        | **Preserving** | Defining water as $\mathrm{H_2O}$. | Conceptual or Symbolic Space |

### Perceptual Space

Every sentence lives in a uniform five-dimensional perceptual space:

- **1 dimension from MP** — modality (possibility, necessity, certainty)
- **1 dimension from VP** — predication (action, process, event)
- **3 dimensions from NP** — the nominal subject (entity in context)

When MP is absent, the sentence carries an implicit assertoric modality ("truly" — the unmarked case). When VP is absent, the sentence carries an implicit existential predicate ("exists" — the unmarked case). These defaults are linked: $VP \to \varepsilon$ if and only if $MP \to \varepsilon$.

Definitive sentences (`S → NP is NP`, `S → NP has NP`) do not fit this pattern. They compare or relate two five-dimensional objects rather than predicating within one.

The implicit "exists" deserves particular attention. A bare noun as sentence — "Fire!" — silently asserts existence. This grammatical convenience mirrors what Buddhist philosophy identifies as the root of conceptual error: treating phenomena as if they possess inherent, permanent selfhood (*svabhāva*). When "exists" is left implicit, the noun appears to exist in its own right, independent of causes and conditions. Making the existential predicate explicit — "fire exists" — restores the processual character of phenomena: existence is something that happens, not something that inheres. See [BuddhistParallels](BuddhistParallels.md#implicit-existence-and-svabhāva) for the full parallel.

#### Prep

Prepositional operators are learned mereological operations on a percetual space where the distance relation is 
geometric (L2) distance as opposed to the embedding similarity of a conceptual space. They are relation-specific 
projections that distinguish containment, support, direction, and vertical ordering.

Since the perceptual space is informed by sensation, regular relative-position biases, 
which supply a natural substrate for "near", "in", "over", and path-like distinctions,
are learned over time.

#### Has

`has` is a **mereological** part operation or an analogue thereof. It links an owner, whole,
or bearer to an attribute, part, or possessed object while keeping those roles
distinct.

Architecturally, it can be expressed by comparing the norm of the area of the constructed whole
to the norm of the area of the sum of the part and the whole. T the degree that those two scalars are 
equal, one is a part of the other.

### Conceptual Space

The mappings below are heuristic correspondences, not claims that a Transformer has
literal built-in `union`, `intersection`, `not`, or `has` modules. The best fit is
usually distributed across three mechanisms:

- relation-specific attention heads, which decide what talks to what
- residual stream updates, which preserve and compose partial meanings
- feed-forward gating, which sharpen, suppress, or reweight features after attention

#### Union via Direct Sum ($\oplus$)

Union is the process of joining independent feature spaces into a single, unified representation.
In **Multi-Head Attention**, the model splits the embedding into $h$ different heads. At the end of the layer, these heads are **united** back together using a direct sum (concatenation). 
This "lifts" the rank, allowing the model to integrate different "points of view" (e.g., syntax, semantics, and context) into a single representation.

Given two tensors $NP \in \mathbb{R}^{N \times 3 \times M}$ and $VP \in \mathbb{R}^{N \times 1 \times M}$, the union $X$ is defined as:
$$X = NP \oplus VP$$
In implementation, this is represented as a **horizontal concatenation** along the feature dimension, resulting in a tensor of shape $N \times 4 \times M$.

The effect is rank lifting:
*   **Dimensionality:** Increases linearly ($3 + 1 = 4$).
*   **Rank Dynamics:** By adding a new, independent slice of data, you increase the **maximum possible CP rank** of the tensor.
*   **Union** "lifts" the data into a higher-dimensional manifold where the model has more "degrees of freedom" to represent complex interactions between the Noun and Verb phrases.

In Transformer terms, the most natural analogue is that different heads each bind a
different relation channel and then return their outputs to a shared residual stream:
$$O_i = \mathrm{softmax}\!\left(\frac{Q_iK_i^\top}{\sqrt{d_h}}\right)V_i,\qquad
\mathrm{Union}(X) \approx [O_1;\dots;O_h]W_O + X$$
One head may bind subject-to-predicate, another predicate-to-object, another
modality-to-clause. The output projection $W_O$ does not erase that separation
immediately; it mixes a set of independently computed slices. That is why union is
the right architectural analogy for predication and argument structure: the model is
not choosing between features, it is carrying several compatible feature bundles at
once and composing them into one larger state.

#### Intersection via Hadamard Masking ($\odot$)

Intersection is the process of isolating specific constituent parts from a composite tensor.
The **Attention Mechanism** itself acts as a sophisticated, learnable Hadamard-style operation.
*   **The Query-Key interaction** produces a set of weights (the mask).
*   **The Softmax output** is applied via a product to the **Value** tensor.
*   This effectively **intersects** the input sequence, "dropping" the rank of unimportant tokens (noise) and isolating the "constituent" tokens necessary for the current task.

To intersect $X$ and retrieve the $VP$ component without changing the tensor's shape, we use a **Binary Mask** $M_{VP}$:
$$VP_{isolated} = X \odot M_{VP}$$
Where $M_{VP}$ is a tensor of the same shape as $X$, containing `1` at the $VP$ indices and `0` elsewhere.

The effect is rank dropping:
*   **Information Filtering:** The Hadamard product acts as a "gate," zeroing out irrelevant features.
*   **Rank Dynamics:** Because many rows/columns are set to zero, the linear dependencies increase, causing the **tensor rank to drop** significantly.
*   **Intersection** effectively projects the high-dimensional composite back into a subspace, focusing the model's attention on a specific constituent.

For modifier structure, the Transformer usually realizes this as a soft compatibility
test between a head concept and its narrowing context. If $h$ is a noun or predicate
state and $g$ is a learned gate extracted from adjectives, determiners, or adverbs,
then a useful approximation is:
$$h' = h \odot g,\qquad g = \sigma(W[h_{\text{modifier}};h_{\text{head}}])$$
This is not a hard symbolic filter but a learned feature mask. A "brown" head
suppresses non-brown regions of the "fox" manifold; a determiner suppresses
indefinite or out-of-context continuations; a manner adverb suppresses incompatible
event readings. In multi-head attention, some heads identify the compatible tokens,
while the MLP following attention sharpens the surviving features. That combined
attention-plus-gating behavior is the architectural core of intersection.

#### Not

Ordinary negation is best modeled as **polarity inversion with scope control** over
an already assembled conceptual object. A negation token does not usually build a
new object from scratch; instead, it attends to an affirmative clause or predicate
and writes back a correction that blocks or reverses its default entailments.

A simple approximation is:
$$h_{\neg X} = h_X \odot (1 - 2g_{\neg})$$
where $g_{\neg}$ is large only on polarity-sensitive dimensions. In a richer model,
the negation head may instead subtract an affirmative feature bundle:
$$h_{\neg X} = h_X - g_{\neg}\odot p_X$$

The main Transformer logic implicated here is:

- one head resolves **scope**: which predicate, adjective, or clause is being negated
- another head carries **polarity**: how the residual stream should be altered
- the residual stream preserves the same proposition-sized object, which is why NOT
  is rank-preserving rather than rank-lifting

So `<not>` corresponds less to feature deletion than to a controlled reversal of
truth-polarity axes inside Conceptual Space.

#### Non

`non-` is not just sentence negation pushed downward. It is closer to **privation**:
the model edits a lexical concept so that it falls outside a familiar subspace
before the full clause is assembled.

A useful approximation is:
$$h_{\text{non-}X} = h_X \odot (1 - m_X) + b_{\text{outside}(X)}$$
where $m_X$ suppresses the canonical feature cluster of $X$, and
$b_{\text{outside}(X)}$ biases the result toward the complement region of that
conceptual field.

The Transformer logic implicated is different from `<not>`:

- a local morpheme or prefix head binds `non` tightly to the following root
- the MLP acts as a **feature suppressor**, removing default property dimensions
- the resulting representation stays near the original lexical neighborhood, but no
  longer occupies its central prototype region

That is why NON is better treated as rank-dropping. It excludes a property from the
concept itself rather than negating a proposition about the concept.

#### Is

`is` is best understood as an **alignment operator**. It forces two conceptual
representations into a common frame and asks whether one should be treated as an
identity, a type-ascription, or a property attribution.

A simple relation score is:
$$s_{\mathrm{is}} = q_{\text{subj}}^\top W_{\mathrm{is}} k_{\text{pred}}$$
and a simple residual update is:
$$h'_{\text{subj}} = h_{\text{subj}} + \alpha W_v h_{\text{pred}}$$
with $\alpha$ determined by the learned compatibility between the two sides.

The Transformer logic implicated is usually:

- similarity heads that compare subject and predicate in a shared basis
- type/prototype heads that recognize `robin is bird` as class membership rather than
  strict token identity
- definitive heads that preserve both operands while adding an explicit relation between
  them in the residual stream

This is why `<is>` is preserving. The sentence does not introduce a third object so
much as stabilize a correspondence between two existing representations. Definitions,
classifications, and predications are all variants of that same alignment problem.

#### Lift

`lift` is the **verb application** operator. It selects a learned [D, D] verb
matrix from a codebook via cosine similarity with the verb embedding, then
applies that matrix to the subject concepts. Two arities are supported:

| Rule              | Arity | Semantics                       |
|-------------------|-------|---------------------------------|
| `lift(C, C)`      | 2     | Intransitive: self-application  |
| `lift(C, C, C)`   | 3     | Transitive: S V O               |

**Binary (intransitive):** The verb selects a matrix from the codebook
and applies it reflexively to the subject: `S' = S + VP_eff @ S`.

**Ternary (transitive):** The object restricts which symbols the verb
activates. Verb and object concept activations are projected to symbolic
space via PiLayer, intersected (element-wise min — the monotonic
analogue of conjunction), then projected back to conceptual activations.
These restricted activations weight the verb content to produce a query
that selects the verb matrix, which is then applied to the subject:

```
verb_act, obj_act  →  PiLayer  →  min(verb_syms, obj_syms)
     →  PiLayer.reverse  →  weight verb content  →  _select_vp
     →  vp_eff [D,D]  →  S + bmm(S, vp_eff)
```

The ternary rule is dispatched when the Grammar's C-tier soft composition
loop finds three consecutive leaves. A variable-step loop consumes two
leaves for ternary rules and one for binary rules. The Grammar stores the
most recent `(S, V, O)` triple for universality evaluation (see
[Ethics.md](./Ethics.md)).

### Symbolic Space

Conjunction, Disjunction, Not, Non, and Is all perform symbolic logic operations within a Symbolic Space, wherein the 0-D symbols have a bijective mapping to concepts.
