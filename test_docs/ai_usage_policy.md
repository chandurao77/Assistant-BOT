# AI and LLM Usage Policy

## Overview

This policy explains how Orbit Labs employees may use large language models (LLMs) at work.

## Preferred Setup: Local Models

- Run models **locally** with Ollama whenever possible. Local models keep prompts and documents on your own machine.
- Recommended chat models: Mistral Nemo 12B for quality, Llama 3.2 3B or Phi-3 Mini on laptops with limited memory.
- Recommended embedding model: `nomic-embed-text`.

## What You May Do

- Summarize meeting notes, logs, and public documentation.
- Draft emails, documentation, and test cases.
- Ask questions about internal documentation using Assistant Bot, which answers only from the documents that have been ingested.

## What You Must Not Do

- Paste Restricted data into any external AI service. Restricted data includes personal data, customer records, credentials, and unreleased financial results.
- Rely on an LLM answer for a decision that needs 100% accuracy without checking the source.
- Use AI-generated code without reviewing it and running the tests. You are responsible for every line you commit.

## Working With Retrieval-Augmented Answers

- Answers from Assistant Bot include source citations. Open the cited page to confirm important details.
- If the assistant says "I don't have enough information", the answer is not in the ingested documents. Add the missing document rather than asking the model to guess.
- Report wrong answers with the thumbs-down button so the team can improve retrieval.

## Evaluating a New Model

1. Run it locally and test it on 20 representative questions.
2. Compare answer accuracy, response time, and memory use against the current default.
3. Record the results in the AI community channel before changing the default model.
