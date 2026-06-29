# Summarize

<!-- version: 1.0.0 -->
<!-- author: Béa -->
<!-- tags: text, utility, summarization -->

Résume un texte long en points clés concis.
Utilise le LLM configuré dans le rôle `fast` (gpt-4o-mini par défaut).

## Usage

Passe le texte à résumer dans `input.text`.
Spécifie optionnellement `input.max_sentences` (défaut: 5).

## Exemple

```json
{
  "text": "Long article about AI...",
  "max_sentences": 3
}
```
