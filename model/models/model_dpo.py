import torch
import torch.nn as nn
import torch.nn.functional as F
import re
import json
from sklearn.metrics.pairwise import cosine_similarity



from transformers import AutoModelForCausalLM, AutoModelForSeq2SeqLM
from models.model_base import PreTrainedModelWrapper
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModel

class AutoDPOModelForCausalLM(PreTrainedModelWrapper):
    """
    An autoregressive model with support for custom modules in addition to the language model.
    This class inherits from `PreTrainedModelWrapper` and wraps a
    `transformers.PreTrainedModel` class. The wrapper class supports classic functions
    such as `from_pretrained`, and `generate`. To call a method of the wrapped
    model, simply manipulate the `pretrained_model` attribute of this class.

    Class attributes:
        - **transformers_parent_class** (`transformers.PreTrainedModel`) -- The parent class of the wrapped model. This
            should be set to `transformers.AutoModelForCausalLM` for this class.
        - **lm_head_namings** (`tuple`) -- A tuple of strings that are used to identify the language model head of the
            wrapped model. This is set to `("lm_head", "embed_out")` for this class but can be changed for other models
            in the future
        - **supported_args** (`tuple`) -- A tuple of strings that are used to identify the arguments that are supported
            by the custom module class you designed. Currently, the supported args are: ______
    """

    transformers_parent_class = AutoModelForCausalLM
    lm_head_namings = ["lm_head", "embed_out"]

    ####################################################################################
    # TODO (Optional): Please put any required arguments for your custom module here
    supported_args = ()
    ####################################################################################

    def __init__(self, pretrained_model, **kwargs):
        r"""
        Initializes the model.

        Args:
            pretrained_model (`transformers.PreTrainedModel`):
                The model to wrap. It should be a causal language model such as GPT2.
                or any model mapped inside the `AutoModelForCausalLM` class.
            kwargs (`dict`, `optional`):
                Additional keyword arguments, that are passed to any `CustomModule` class.
        """
        super().__init__(pretrained_model, **kwargs)
        
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # self.device = torch.device("cpu")
        # self.device = torch.device("mps")
        self.pretrained_model.to(self.device)

        print(f"Using device: {self.device}")   
        output_path = "./documents/embeddings/all_pdfs_embeddings.json"
        with open(output_path, 'r') as f:
            data = json.load(f)
            self.all_embeddings = data['embeddings']
            self.all_chunks = data['chunks']

        self.embedding_tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-mpnet-base-v2")
        self.embedding_model = AutoModel.from_pretrained("sentence-transformers/all-mpnet-base-v2")

        if not any(hasattr(self.pretrained_model, attribute) for attribute in self.lm_head_namings):
            raise ValueError("The model does not have a language model head, please use a model that has one.")

        ###########################################################################################
        # TODO (Optional): Please uncomment the following lines to initialize your custom module
        # Make sure CustomModule is repalced with the name of your custom module class
        # Remember that the below lines are just an example
        # You can reanme the class and the variabels to fit your custom module name,
        # just make sure they are consistent in the code
        # =========================================================================================

        # custom_module_kwargs, _, _ = self._split_kwargs(kwargs)
        # self.custom_module = CustomModule(self.pretrained_model.config, **custom_module_kwargs)
        # self._init_weights(**custom_module_kwargs)
        ###########################################################################################

    def _init_weights(self, **kwargs):
        """
        Initializes the weights of the custom module. The default initialization strategy is random.
        Users can pass a different initialization strategy by passing the `custom_module_init_strategy`
        argument when calling `.from_pretrained`. Supported strategies are:
            - `normal`: initializes the weights with a normal distribution.

        Args:
            **kwargs (`dict`, `optional`):
                Additional keyword arguments, that are passed to the `CustomModule` class.
        """
        ###############################################################
        # TODO (Optional): Please implement the initialization strategy for your custom module here
        pass
        ###############################################################

    def state_dict(self, *args, **kwargs):
        """
        Returns the state dictionary of the model. We add the state dictionary of the custom module
        to the state dictionary of the wrapped model by prepending the key with `custom_module.`.

        IMPORTANT: Make sure to replace `custom_module` with the name of your custom module class name.
        """
        if not self.is_peft_model:
            pretrained_model_state_dict = self.pretrained_model.state_dict(*args, **kwargs)
        else:
            pretrained_model_state_dict = {}

        ###########################################################################################
        # TODO (Optional): Please uncomment the following lines to initialize your custom module
        # Make sure "custom_module" is repalced with the name of your custom module class
        # =========================================================================================
        # custom_module_state_dict = self.custom_module.state_dict(*args, **kwargs)
        # for k, v in custom_module_state_dict.items():
        #     pretrained_model_state_dict[f"custom_module.{k}"] = v
        ###########################################################################################
        return pretrained_model_state_dict

    def post_init(self, state_dict):
        """
        We add the state dictionary of the custom module to the state dictionary of the wrapped model
        by prepending the key with `custom_module.`. This function removes the `custom_module.` prefix from the
        keys of the custom module state dictionary.

        IMPORTANT: Make sure to replace `custom_module` with the name of your custom module class name.
        """
        if not hasattr(self, 'custom_module'):
            return

        for k in list(state_dict.keys()):
            if "custom_module." in k:
                state_dict[k.replace("custom_module.", "")] = state_dict.pop(k)
        self.custom_module.load_state_dict(state_dict, strict=False)
        del state_dict

        if hasattr(self.pretrained_model, "hf_device_map"):
            if (
                "cpu" in self.pretrained_model.hf_device_map.values()
                or "disk" in self.pretrained_model.hf_device_map.values()
            ):
                raise ValueError(
                    "The model is offloaded on CPU or disk - CPU & disk offloading is not supported for CustomModule models."
                )

            # get the lm_head device
            for name, module in self.pretrained_model.named_modules():
                if any(attribute in name for attribute in self.lm_head_namings):
                    lm_head_device = module.weight.device
                    break

            # put custom_module on the same device as the lm_head to avoid issues
            self.custom_module = self.custom_module.to(lm_head_device)

            def set_device_hook(module, input, outputs):
                r"""
                A hook that sets the device of the output of the model to the device of the first
                parameter of the model.

                Args:
                    module (`nn.Module`):
                        The module to which the hook is attached.
                    input (`tuple`):
                        The input to the module.
                    outputs (`tuple`):
                        The output of the module.
                """
                new_output = ()
                for output in outputs:
                    if isinstance(output, torch.Tensor):
                        new_output += (output.to(lm_head_device),)
                    else:
                        new_output += (output,)
                return new_output

            self.register_forward_hook(set_device_hook)
            self.is_sequential_parallel = True

    def push_to_hub(self, *args, **kwargs):
        """Push the model to the Hugging Face hub."""
        ###########################################################################################
        # TODO (Optional): Please uncomment the following line to add the custom module to the hub model
        # Make sure custom_module is repalced with the name of your custom module class
        # =========================================================================================
        # self.pretrained_model.custom_module = self.custom_module
        ###########################################################################################

        return self.pretrained_model.push_to_hub(*args, **kwargs)

    def forward(
        self,
        input_ids=None,
        past_key_values=None,
        attention_mask=None,
        **kwargs,
    ):
        """
        Applies a forward pass to the wrapped model and returns the output from the model.

        Args:
            input_ids (`torch.LongTensor` of shape `(batch_size, sequence_length)`):
                Indices of input sequence tokens in the vocabulary.
            past_key_values (`tuple(tuple(torch.FloatTensor))`, `optional`):
                Contains pre-computed hidden-states (key and values in the attention blocks) as computed by the model
                (see `past_key_values` input) to speed up sequential decoding.
            attention_mask (`torch.FloatTensor` of shape `(batch_size, sequence_length)`, `optional`):
                Mask to avoid performing attention on padding token indices. Mask values selected in ``[0, 1]``:
                - 1 for tokens that are **not masked**,
                - 0 for tokens that are **masked**.
            kwargs (`dict`, `optional`):
                Additional keyword arguments, that are passed to the wrapped model.
        Returns:
            output_dict (`dict`): A dictionary containing the output from the model.
        """
        kwargs["output_hidden_states"] = True
        kwargs["past_key_values"] = past_key_values

        if self.is_peft_model and self.pretrained_model.active_peft_config.peft_type == "PREFIX_TUNING":
            kwargs.pop("past_key_values")

        outputs = self.pretrained_model(input_ids=input_ids, attention_mask=attention_mask, **kwargs)

        output_dict = {
            "logits": outputs.logits,
            "hidden_states": outputs.hidden_states,
            "past_key_values": outputs.past_key_values,
        }

        return output_dict
    
    
    def get_logprobs(self, batch, tokenizer):
        """
        Computes the log probabilities of a response using the model respectively.

        Args:
            batch (`dict` of `list`): A dictionary containing the input data for the DPO model.
                The data format is as follows:
                {
                    "prompt": List[str],
                    "chosen": List[str],
                    "rejected": List[str],
                    "chosen_logps": Optional(torch.FloatTensor)
                    "rejected_logps": Optional(torch.FloatTensor)
                }
            tokenizer (`PreTrainedTokenizerBase`): The tokenizer used to tokenize the input data.
        Returns:
            A tuple of two tensors: (chosen_logps, rejected_logps)
            chosen_logps (`torch.FloatTensor`):
                Log probabilities of the chosen responses. Shape: (batch_size,)
            rejected_logps (`torch.FloatTensor`):
                Log probabilities of the rejected responses. Shape: (batch_size,)
        """
        ###############################################################
        # =============================================================

        tokenizer.pad_token = tokenizer.eos_token
                  
        prompt_texts = ["<|im_start|>system\nYou are a helpful AI assistant.<|im_end|>\n<|im_start|>user\n"+prompt+"<|im_end|>\n"+"<|im_start|>assistant\n" for prompt in batch["prompt"]]
        chosen_texts = [prompt+ "<|im_start|>assistant\n"+chosen+"<|im_end|>\n"  for prompt, chosen in zip(prompt_texts, batch["chosen"])]
        rejected_texts = [prompt+ "<|im_start|>assistant\n"+rejected+"<|im_end|>\n"  for prompt, rejected in zip(prompt_texts, batch["rejected"])]
      
        # prompt_texts = batch['prompt']
        # chosen_texts = [prompt+ chosen  for prompt, chosen in zip(prompt_texts, batch["chosen"])]
        # rejected_texts = [prompt+ rejected  for prompt, rejected in zip(prompt_texts, batch["rejected"])]
      

        inputs = tokenizer(prompt_texts, return_tensors="pt", padding=True, truncation=True).to(self.device)
        chosen_inputs = tokenizer(chosen_texts, return_tensors="pt", padding=True, truncation=True).to(self.device)
        rejected_inputs = tokenizer(rejected_texts, return_tensors="pt", padding=True, truncation=True).to(self.device)

        with torch.no_grad():
            chosen_outputs = self.forward(input_ids=chosen_inputs["input_ids"], attention_mask=chosen_inputs["attention_mask"])
            rejected_outputs = self.forward(input_ids=rejected_inputs["input_ids"], attention_mask=rejected_inputs["attention_mask"])
        chosen_logps = F.log_softmax(chosen_outputs['logits'], dim=-1)
        rejected_logps = F.log_softmax(rejected_outputs['logits'], dim=-1)

        chosen_logps = torch.gather(chosen_logps, 2, chosen_inputs["input_ids"].unsqueeze(-1)).squeeze(-1).sum(dim=1)
        rejected_logps = torch.gather(rejected_logps, 2, rejected_inputs["input_ids"].unsqueeze(-1)).squeeze(-1).sum(dim=1)
        
        ###############################################################
        
        return chosen_logps.cpu(), rejected_logps.cpu()
    
                               

    def prediction_step_reward(
        self,
        policy_chosen_logps: torch.FloatTensor,
        policy_rejected_logps: torch.FloatTensor,
        reference_chosen_logps: torch.FloatTensor,
        reference_rejected_logps: torch.FloatTensor,
    ):
        """
        Computes the reward socres of the chosen and reject responses by implementing the DPO reward function
        Reference of the DPO reward function: https://arxiv.org/pdf/2305.18290.pdf

        Args:
            policy_chosen_logps (`torch.FloatTensor`):
                Log probabilities of the policy model for the chosen responses. Shape: (batch_size,)
            policy_rejected_logps (`torch.FloatTensor`):
                Log probabilities of the policy model for the rejected responses. Shape: (batch_size,)
            reference_chosen_logps (`torch.FloatTensor`):
                Log probabilities of the reference model for the chosen responses. Shape: (batch_size,)
            reference_rejected_logps (`torch.FloatTensor`):
                Log probabilities of the reference model for the rejected responses. Shape: (batch_size,)
        Returns:
            output_dict (`dict`):
                A dictionary containing the reward scores of the chosen and rejected responses.
        """
        # output_dict = {
        #     "chosen_rewards": [],
        #     "rejected_rewards": []
        # }

        ########################################################################
        # TODO: Please implement the prediction step that computes the rewards
        # ======================================================================
        # You need to return one reward score for each chosen and rejected response.
        # ======================================================================
        chosen_rewards = []
        rejected_rewards = []

        for pc_logp, pr_logp, rc_logp, rr_logp in zip(policy_chosen_logps, policy_rejected_logps, reference_chosen_logps, reference_rejected_logps):
            chosen_reward = pc_logp - rc_logp
            rejected_reward = pr_logp - rr_logp

            chosen_rewards.append(chosen_reward)
            rejected_rewards.append(rejected_reward)

        output_dict = {
            "chosen_rewards": torch.stack(chosen_rewards),
            "rejected_rewards": torch.stack(rejected_rewards)
        }

        return output_dict

    def mean_pooling(self,model_output, attention_mask):
        token_embeddings = model_output[0]  # First element of model_output contains all token embeddings
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)


    def embed_prompt(self,prompt, model, tokenizer):
        encoded_input = tokenizer(prompt, return_tensors='pt', truncation=True, padding=True)
        with torch.no_grad():
            model_output = model(**encoded_input)
        prompt_embedding = self.mean_pooling(model_output, encoded_input['attention_mask'])        
        prompt_embedding = F.normalize(prompt_embedding, p=2, dim=1)
        return prompt_embedding.squeeze().numpy()
    
    def retrieve_top_chunks(self,prompt_embedding, embeddings, chunks, top_k=3):
        similarities = cosine_similarity([prompt_embedding], embeddings)[0]
        top_indices = similarities.argsort()[-top_k:][::-1]
        return [chunks[i] for i in top_indices], [similarities[i] for i in top_indices]



    def prediction_step_mcqa(self, batch, tokenizer):
        """
        Computes the mcqa prediction of the given question.

        Args:
            batch (`dict` of `list`):
                A dictionary containing the input mcqa data for the DPO model.
                The data format is as follows:
                {
                    "question": List[str], each <str> contains the question body and the choices
                    "answer": List[str], each <str> is a single letter representing the correct answer
                }
            tokenizer (`PreTrainedTokenizerBase`): The tokenizer used to tokenize the input questions.
        Returns:
            output_dict (`dict`): A dictionary containing the model predictions given input questions.
        """
        output_dict = {"preds": []}

        ########################################################################
        # TODO: Please implement the prediction step that generates the prediction of the given MCQA question
        # ======================================================================
        # You need to return one letter prediction for each question.
        # ======================================================================
        ########################################################################
        device = self.device
        SYSTEM_PROMPT = "You are an AI tutor specialized in Multiple-Choice Question Answering (MCQA). Make sure to give the letter choice \n"
        for question_and_choices in batch['question']:
            # Create the initial input text for the model
            prompt_embedding = self.embed_prompt(question_and_choices, self.embedding_model, self.embedding_tokenizer)
            top_chunks, _ = self.retrieve_top_chunks(prompt_embedding, self.all_embeddings, self.all_chunks)

            initial_input = f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|> <|im_start|>context\n {''.join(top_chunks)} <|im_end|> <|im_start|>\nuser\n {question_and_choices} <|im_end|> \n <|im_start|> assistant\n "
            # Tokenize the initial input and move tensors to the correct device
            inputs = tokenizer(initial_input, return_tensors="pt").to(device)

            # Generate the initial response
            with torch.no_grad():
                model_outputs = self.pretrained_model.generate(**inputs,max_new_tokens=128)

            # Decode the initial response
            initial_response = tokenizer.decode(model_outputs[0], skip_special_tokens=False)
            initial_response = initial_response.split("<|im_start|> assistant")[1]
            #print(initial_response)

            SYSTEM_PROMPT2= "You will be having a question and a response and I want you to extract the MCQ choise letter. respond with the following format: [The chosen letter is _] where _ is the letter of the correct choice. (A,B,C,D,..). Don't focus on the question itself just extract the answer. Please respect the format that i gave you and make sure that it is the letter\n"
            second_input = f"<|im_start|>system\n {SYSTEM_PROMPT2} <|im_end|>  <|im_start|>\nuser\n {question_and_choices} response: {initial_response}. Don't forget to use the format [The chosen letter is _] where _ is the letter of the correct choice. (A,B,C,D,..) Don't focus on the question itself just extract the letter <|im_end|> \n <|im_start|>assistant\n  "
            
            second_inputs = tokenizer(second_input, return_tensors="pt").to(device)
            with torch.no_grad():
                second_model_outputs = self.pretrained_model.generate(**second_inputs,max_new_tokens=256)

            second_response = tokenizer.decode(second_model_outputs[0], skip_special_tokens=True)
            #print(second_response)
            #print("***************")

            # take the last token as the choice letter
            try:
              choice = second_response.split("The chosen letter is ")[3]
              choice = choice[0]
              if choice not in "ABCDEFGHIJ":
                raise ValueError("The chosen letter is not an uppercase alphabet letter.")
            except (IndexError, ValueError):
              try:
                choice = second_response.split("Answer: response: \n")[1]
                choice = choice[0]
                if choice not in "ABCDEFGHIJ":
                  raise ValueError("The chosen letter is not an uppercase alphabet letter.")
              except (IndexError, ValueError):
                #print("RANDOM")
                choice ="A"

            # Append the prediction to the output dictionary
            output_dict["preds"].append(choice)
            #print(f"the chosen letter is {choice}")

        return output_dict
    

class AutoDPOModelForSeq2SeqLM(PreTrainedModelWrapper):
    r"""
    A seq2seq model with support for custom modules in addition to the transformer model.
    This class inherits from `~trl.PreTrainedModelWrapper` and wraps a
    `transformers.PreTrainedModel` class. The wrapper class supports classic functions
    such as `from_pretrained` and `push_to_hub` and also provides some additional
    functionalities such as `generate`.

    Args:
        pretrained_model (`transformers.PreTrainedModel`):
            The model to wrap. It should be a causal language model such as GPT2.
            or any model mapped inside the `AutoModelForSeq2SeqLM` class.
        kwargs:
            Additional keyword arguments passed along to any `CustomModule` classes.
    """

    transformers_parent_class = AutoModelForSeq2SeqLM
    lm_head_namings = ["lm_head", "embed_out", "output_projection"]
    ####################################################################################
    # TODO (Optional): Please put any required arguments for your custom module here
    supported_args = ()
    ####################################################################################

    def __init__(self, pretrained_model, **kwargs):
        super().__init__(pretrained_model, **kwargs)
        self.is_encoder_decoder = True
        if not self._has_lm_head():
            raise ValueError("The model does not have a language model head, please use a model that has one.")

        ###########################################################################################
        # TODO (Optional): Please uncomment the following lines to initialize your custom module
        # Make sure CustomModule is repalced with the name of your custom module class
        # Remember that the below lines are just an example
        # You can reanme the class and the variabels to fit your custom module name,
        # just make sure they are consistent in the code
        # =========================================================================================
        # custom_module_kwargs, _, _ = self._split_kwargs(kwargs)
        # self.custom_module = CustomModule(self.pretrained_model.config, **custom_module_kwargs)
        # self._init_weights(**custom_module_kwargs)
        ###########################################################################################

    def _has_lm_head(self):
        # check module names of all modules inside `pretrained_model` to find the language model head
        for name, _module in self.pretrained_model.named_modules():
            if any(attribute in name for attribute in self.lm_head_namings):
                return True
        return False

    def _init_weights(self, **kwargs):
        """
        Initializes the weights of the custom module. The default initialization strategy is random.
        Users can pass a different initialization strategy by passing the `custom_module_init_strategy`
        argument when calling `.from_pretrained`. Supported strategies are:
            - `normal`: initializes the weights with a normal distribution.

        Args:
            **kwargs (`dict`, `optional`):
                Additional keyword arguments, that are passed to the `CustomModule` class.
        """
        ###############################################################
        # TODO (Optional): Please implement the initialization strategy for your custom module here
        pass
        ###############################################################

    def state_dict(self, *args, **kwargs):
        """
        Returns the state dictionary of the model. We add the state dictionary of the custom module
        to the state dictionary of the wrapped model by prepending the key with `custom_module.`.

        IMPORTANT: Make sure to replace `custom_module` with the name of your custom module class name.
        """
        if not self.is_peft_model:
            pretrained_model_state_dict = self.pretrained_model.state_dict(*args, **kwargs)
        else:
            pretrained_model_state_dict = {}

        ###########################################################################################
        # TODO (Optional): Please uncomment the following lines to initialize your custom module
        # Make sure "custom_module" is repalced with the name of your custom module class
        # =========================================================================================
        # custom_module_state_dict = self.custom_module.state_dict(*args, **kwargs)
        # for k, v in custom_module_state_dict.items():
        #     pretrained_model_state_dict[f"custom_module.{k}"] = v
        ###########################################################################################
        return pretrained_model_state_dict

    def post_init(self, state_dict):
        r"""
        We add the state dictionary of the custom module to the state dictionary of the wrapped model
        by prepending the key with `custom_module.`. This function removes the `custom_module.` prefix from the
        keys of the custom module state dictionary.

        IMPORTANT: Make sure to replace `custom_module` with the name of your custom module class name.
        """
        if not hasattr(self, 'custom_module'):
            return

        for k in list(state_dict.keys()):
            if "custom_module." in k:
                state_dict[k.replace("custom_module.", "")] = state_dict.pop(k)
        self.custom_module.load_state_dict(state_dict, strict=False)
        del state_dict

        if hasattr(self.pretrained_model, "hf_device_map"):
            if (
                "cpu" in self.pretrained_model.hf_device_map.values()
                or "disk" in self.pretrained_model.hf_device_map.values()
            ):
                raise ValueError(
                    "The model is offloaded on CPU or disk - CPU & disk offloading is not supported for CustomModule models."
                )

            # get the lm_head device
            for name, module in self.pretrained_model.named_modules():
                if any(attribute in name for attribute in self.lm_head_namings):
                    lm_head_device = module.weight.device
                    break

            # put custom_module on the same device as the lm_head to avoid issues
            self.custom_module = self.custom_module.to(lm_head_device)

            def set_device_hook(module, input, outputs):
                r"""
                A hook that sets the device of the output of the model to the device of the first
                parameter of the model.

                Args:
                    module (`nn.Module`):
                        The module to which the hook is attached.
                    input (`tuple`):
                        The input to the module.
                    outputs (`tuple`):
                        The output of the module.
                """
                new_output = ()
                for output in outputs:
                    if isinstance(output, torch.Tensor):
                        new_output += (output.to(lm_head_device),)
                    else:
                        new_output += (output,)
                return new_output

            self.register_forward_hook(set_device_hook)
            self.is_sequential_parallel = True

    def push_to_hub(self, *args, **kwargs):
        """Push the model to the Hugging Face hub."""
        ###########################################################################################
        # TODO (Optional): Please uncomment the following line to add the custom module to the hub model
        # Make sure custom_module is repalced with the name of your custom module class
        # =========================================================================================
        # self.pretrained_model.custom_module = self.custom_module
        ###########################################################################################

        return self.pretrained_model.push_to_hub(*args, **kwargs)

    def forward(
        self,
        input_ids=None,
        past_key_values=None,
        attention_mask=None,
        **kwargs,
    ):
        r"""
        Applies a forward pass to the wrapped model and returns the output from the model.

        Args:
            input_ids (`torch.LongTensor` of shape `(batch_size, sequence_length)`):
                Indices of input sequence tokens in the vocabulary.
            past_key_values (`tuple(tuple(torch.FloatTensor))`, `optional`):
                Contains pre-computed hidden-states (key and values in the attention blocks) as computed by the model
                (see `past_key_values` input) to speed up sequential decoding.
            attention_mask (`torch.FloatTensor` of shape `(batch_size, sequence_length)`, `optional`):
                Mask to avoid performing attention on padding token indices. Mask values selected in ``[0, 1]``:
                - 1 for tokens that are **not masked**,
                - 0 for tokens that are **masked**.
            kwargs (`dict`, `optional`):
                Additional keyword arguments, that are passed to the wrapped model.
        Returns:
            ouput_dict (`dict`): A dictionary containing the output from the model.
        """
        kwargs["output_hidden_states"] = True
        kwargs["past_key_values"] = past_key_values

        if self.is_peft_model and self.pretrained_model.active_peft_config.peft_type == "PREFIX_TUNING":
            kwargs.pop("past_key_values")

        ouput_dict = {}

        ###############################################################
        # TODO: Please implement your customized forward pass here
        # =============================================================
        raise NotImplementedError
        ###############################################################

        return ouput_dict

    def get_logprobs(self, batch, tokenizer):
        """
        Computes the log probabilities of a response using the model respectively.

        Args:
            batch (`dict` of `list`): A dictionary containing the input data for the DPO model.
                The data format is as follows:
                {
                    "prompt": List[str],
                    "chosen": List[str],
                    "rejected": List[str],
                    "chosen_logps": Optional(torch.FloatTensor)
                    "rejected_logps": Optional(torch.FloatTensor)
                }
            tokenizer (`PreTrainedTokenizerBase`): The tokenizer used to tokenize the input data.
        Returns:
            A tuple of two tensors: (chosen_logps, rejected_logps)
            chosen_logps (`torch.FloatTensor`):
                Log probabilities of the chosen responses. Shape: (batch_size,)
            rejected_logps (`torch.FloatTensor`):
                Log probabilities of the rejected responses. Shape: (batch_size,)
        """
        ###############################################################
        # TODO: Please implement your customized logprob computation here
        # =============================================================
        raise NotImplementedError
        ###############################################################

        return chosen_logps, rejected_logps

    def prediction_step_reward(
        self,
        policy_chosen_logps: torch.FloatTensor,
        policy_rejected_logps: torch.FloatTensor,
        reference_chosen_logps: torch.FloatTensor,
        reference_rejected_logps: torch.FloatTensor,
    ):
        """
        Computes the reward socres of the chosen and reject responses by implementing the DPO reward function
        Reference of the DPO reward function: https://arxiv.org/pdf/2305.18290.pdf

        Args:
            policy_chosen_logps (`torch.FloatTensor`):
                Log probabilities of the policy model for the chosen responses. Shape: (batch_size,)
            policy_rejected_logps (`torch.FloatTensor`):
                Log probabilities of the policy model for the rejected responses. Shape: (batch_size,)
            reference_chosen_logps (`torch.FloatTensor`):
                Log probabilities of the reference model for the chosen responses. Shape: (batch_size,)
            reference_rejected_logps (`torch.FloatTensor`):
                Log probabilities of the reference model for the rejected responses. Shape: (batch_size,)
        Returns:
            output_dict (`dict`):
                A dictionary containing the reward scores of the chosen and rejected responses.
        """
        output_dict = {
            "chosen_rewards": [],
            "rejected_rewards": []
        }

        ########################################################################
        # TODO: Please implement the dpo loss function to compute the rewards
        # You need to return one reward score for each chosen and rejected response.
        # ======================================================================
        raise NotImplementedError
        ########################################################################

        return output_dict

    def prediction_step_mcqa(self, batch, tokenizer):
        """
        Computes the mcqa prediction of the given question.

        Args:
            batch (`list` of `dict`):
                A list of dictionaries containing the input mcqa data for the DPO model.
                The data format is as follows:
                {
                    "question": str,
                    "choices": List[str],
                    "answer": str,
                }
            tokenizer (`PreTrainedTokenizerBase`): The tokenizer used to tokenize the input questions.
        Returns:
            output_dict (`dict`): A dictionary containing the model predictions given input questions.
        """
        output_dict = {"preds": []}

        ########################################################################
        # TODO: Please implement the prediction step that generates the prediction of the given MCQA question
        # ======================================================================
        # You need to return one letter prediction for each question.
        # ======================================================================
        raise NotImplementedError
        ########################################################################

        return output_dict