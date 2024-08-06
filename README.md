# EPFL MISTRAL MIND CHATBOT

## Project Information
- **Project Title:** EPFL Mistral Mind Chatbot
- **Authors:**
  - Mohamed Charfi
  - Yacine Chaouch
  - Aziz Laadhar

## Introduction
The EPFL Chatbot is a specialized language model developed to address the limitations of general-purpose large language models (LLMs) in educational settings. The chatbot is tailored to the curriculum of EPFL, using fine-tuning and RAG techniques to leverage relevant data sources. This approach aims to create a customized tool that meets the specific needs of EPFL students.

## Methodology
### Data Collection and Training
- **Data Sources:** EPFL-specific resources, Anthropic HH RLHF dataset, MMLU-STEM, GSM8K, EPFL Preference Dataset, SetFit dataset.
- **Training Techniques:**
  - **Direct Preference Optimization (DPO):** Ensures coherent and ethical responses.
  - **Supervised Fine-Tuning (SFT):** Specializes the model in handling multiple-choice questions.
  - **Retrieval-Augmented Generation (RAG):** Integrates dynamic information retrieval to enhance context-awareness.

### Model Training
- **Base Model:** Mistral 7B
- **Techniques Used:**
  - Fine-tuning with DPO and RAG
  - Quantization for efficiency
  - SFT using LoRA adapters

## Experiments
### MCQ Specialization
- **Dataset:** 6,000 samples from the SciQ dataset, randomized correct answer placement.
- **Results:** Effective fine-tuning with specific hyper-parameter settings for LoRA.

### RAG Implementation
- **Data Collection:** EPFL textbooks and student notes.
- **Embedding Model:** "all-mpnet-base-v2" from sentence-transformers.
- **Chunking:** Text broken into 200-word chunks with a 50-word overlap.
- **Retrieval Process:** Semantic search to find and concatenate relevant chunks with the prompt.

## Evaluation
- **Dataset:** 300 MCQ questions curated from previous exams.
- **Models Compared:** Base Mistral, Mistral + DPO, Mistral + RAG, Mistral + DPO + RAG.
- **Results:** Modest improvements with DPO and RAG.

## Ethical Considerations
- **Data Privacy:** Access restricted to EPFL students.
- **Bias and Fairness:** Ensured through diverse training data and ethical guidelines.
- **Transparency:** Documentation of capabilities and limitations.
- **Accessibility:** Future work includes integrating sign language recognition.

## Conclusion
The EPFL Chatbot demonstrates the potential of specialized language models in educational settings. While initial results show modest improvements with DPO and RAG, further refinement is needed for substantial gains. The project contributes to the development of effective, domain-specific educational tools.

---

For more details, please refer to the report [here](https://github.com/charfimohamed/education_related_chatbot/blob/main/pdfs/lasmer.pdf).
