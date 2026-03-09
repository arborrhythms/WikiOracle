# Grammar

This grammar renders English as XML with a small fixed inventory. It favors three things over full formal rigor:

- every surface token stays visible
- narrowing and broadening are explicit
- operator application is marked explicitly

## Inventory

### Operators
- `<intersection>`: binary narrowing composition
- `<union>`: binary broadening composition
- `<not>`: unary negation
- `<non>`: unary privative or exclusionary operator
- `<lift>`: binary operator application or dimensional augmentation
- `<is>`: identity or definition

### Leaves
- `<n word="..."/>`: noun
- `<adj word="..."/>`: adjective
- `<v word="..."/>`: verb
- `<adv word="..."/>`: adverb
- `<lifter word="..."/>`: function word or structural word
- `<punct word="..."/>`: punctuation

## Surface-Preservation Rule

Every surface token should appear somewhere as a leaf. The operators carry the composition; the leaves preserve the visible words.

Semantic arity:

- `intersection`, `union`, `lift`, `is`: binary
- `not`, `non`: unary

To preserve the surface string, an operator may also contain lexical witness leaves such as `<lifter word="and"/>`. For copular clauses, prefer putting the surface copula on the operator itself, for example `<is word="is">...</is>`. Terminal punctuation should usually sit outside the clause operator as its own leaf.

## Copula-First Rule

Before mapping a clause to an ordinary verb phrase, check whether it is definitional, classificatory, part-whole, or about language itself.

Use `<is>` first when:

- the sentence equates one thing with another
- the sentence defines a term
- the sentence says one thing is a kind, member, or part of another
- the sentence attributes a property by means of a copula rather than an event verb
- the sentence is about a word, label, or linguistic expression

Examples:

- `water is h2o` -> prefer `<is>`
- `a robin is a bird` -> prefer `<is>`
- `water is wet` -> prefer `<is>`, not an ordinary eventive `<v>`

Preserve the surface copula on the operator itself, for example `<is word="is">...</is>`, but do not let that force the whole clause into the ordinary `lift + v` pattern.

## Main Example

Surface sentence:

`The quick brown fox probably jumps over the lazy dog and the sleepy cat.`

Parse:

```xml
<lift>
  <adv word="probably"/>
  <lift>
    <lift>
      <v word="jumps"/>
      <lift>
        <lifter word="over"/>
        <union>
          <lifter word="and"/>
          <intersection>
            <lifter word="the"/>
            <intersection>
              <adj word="lazy"/>
              <n word="dog"/>
            </intersection>
          </intersection>
          <intersection>
            <lifter word="the"/>
            <intersection>
              <adj word="sleepy"/>
              <n word="cat"/>
            </intersection>
          </intersection>
        </union>
      </lift>
    </lift>
    <intersection>
      <lifter word="the"/>
      <intersection>
        <adj word="quick"/>
        <intersection>
          <adj word="brown"/>
          <n word="fox"/>
        </intersection>
      </intersection>
    </intersection>
  </lift>
</lift>
<punct word="."/>
```

Reading:

```text
probably((jumps(over(the(lazy(dog)) union the(sleepy(cat)))))(the(quick(brown(fox)))))
```

## What The Operators Mean

- `<intersection>`: use when composition makes the result narrower or more specific.
  Example: `brown fox`, `quick brown fox`, `the fox`.
- `<union>`: use when composition broadens, accumulates, or lists alternatives.
  Example: `dog or cat`, and sometimes broadening `dog and cat`.
- `<lift>`: use when one expression takes another as an argument and creates a higher-dimensional construct.
  Example: `over(the dog)`, `jumps(over(...))`, `probably(S)`.
- `<not>`: ordinary sentence or predicate negation.
- `<non>`: lexical privation such as `nonhuman`, `nonzero`.
- `<is>`: identity, equivalence, definition, classification, or parthood.

## Minimal Examples

Definition:

```xml
<is word="is">
  <n word="water"/>
  <n word="h2o"/>
</is>
<punct word="."/>
```

Classification:

```xml
<is word="is">
  <intersection>
    <lifter word="a"/>
    <n word="robin"/>
  </intersection>
  <intersection>
    <lifter word="a"/>
    <n word="bird"/>
  </intersection>
</is>
<punct word="."/>
```

Copular predication:

```xml
<is word="is">
  <n word="water"/>
  <adj word="wet"/>
</is>
<punct word="."/>
```

Negation:

```xml
<not>
  <adv word="not"/>
  <lift>
    <v word="jump"/>
    <intersection>
      <lifter word="the"/>
      <n word="fox"/>
    </intersection>
  </lift>
</not>
<punct word="."/>
```

## Suggested Mappings Into This Inventory

| English item | Default mapping | Notes |
|---|---|---|
| common noun, proper noun, pronoun, nominal numeral | `<n>` | `alice`, `she`, `three` |
| adjective, participle-as-modifier, ordinal, noun modifier | `<adj>` | `broken`, `first`, `chicken` in `chicken soup` |
| main verb, auxiliary with real verbal force | `<v>` | `runs`, `jumped`, `slept` |
| adverb, sentence adverb, modal adverb | `<adv>` | `quickly`, `probably`, `maybe` |
| determiner, article, preposition, particle, complementizer, coordinator, infinitival `to`, unknown function word | `<lifter>` | `the`, `over`, `that`, `and`, `to` |
| punctuation | `<punct>` | `. , ; : ? !` |

Practical special cases:

- Articles and determiners usually appear as `lifter` under `intersection`.
- Prepositions usually appear as `lifter` under `lift`.
- Surface `and` and `or` are usually preserved as `lifter` witnesses inside `union`.
- Modal adverbs such as `probably` usually stay `adv` and take scope by being the left child of an outer `lift`.
- Modal auxiliaries such as `must`, `should`, and `can` can be mapped to `lifter` if you want to preserve them without adding a new leaf class.
- Copular forms such as `is`, `are`, `was`, and `were` should be tested against `<is>` before falling back to `<v>`, and when they are used that way they should usually appear as the operator attribute, for example `<is word="is">`.
- Terminal punctuation should usually be emitted outside the clause operator it closes.

## Short Parsing Procedure

1. Keep every surface token.
2. Map visible words to `n`, `adj`, `v`, `adv`, `lifter`, or `punct`.
3. Before using `<v>`, test whether the clause is better represented by `<is>`.
4. Build noun phrases from the head outward with `intersection`.
5. Use `union` only when the result broadens or coordinates alternatives.
6. Use `lift` whenever a word or phrase takes an argument.
7. Use `is` for identity, definition, property attribution, classification, and parthood.
8. Use `not` for ordinary negation and `non` for lexical privation.
9. If uncertain, preserve the word and choose the least committal fallback:
   - unknown content word -> `n`
   - unknown function word -> `lifter`

## Boole, And/Or, Union/Intersection

The relevant point from George Boole is simple: class combination has an intersection side and a union side. Intersection narrows; union broadens. This grammar uses the names `intersection` and `union` directly so it does not have to overload English `and`, English `or`, and Boolean operator names all at once.

That means:

- `brown things ∩ fox things` -> brown foxes
- `dogs ∪ cats` -> dogs-or-cats, or a broadened coordinated set

## Limits

- This is a compact parse grammar, not a complete formal semantics.
- Some surface distinctions are intentionally collapsed.
- Witness leaves keep the sentence recoverable even when the structural parse is imperfect.
- The price of that recoverability is that some nodes contain surface witnesses in addition to their semantic operands.
