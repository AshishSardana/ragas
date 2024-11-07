from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass

import numpy as np

from ragas.prompt import PydanticPrompt
from ragas.testset.graph import KnowledgeGraph
from ragas.testset.persona import Persona, PersonaList
from ragas.testset.synthesizers.multi_hop.base import (
    MultiHopQuerySynthesizer,
    MultiHopScenario,
)
from ragas.testset.synthesizers.multi_hop.prompts import QueryAnswerGenerationPrompt
from ragas.testset.synthesizers.prompts import (
    ThemesPersonasInput,
    ThemesPersonasMatchingPrompt,
)

if t.TYPE_CHECKING:
    from langchain_core.callbacks import Callbacks

logger = logging.getLogger(__name__)


@dataclass
class MultiHopSpecificQuerySynthesizer(MultiHopQuerySynthesizer):
    """
    Synthesizes overlap based queries by choosing specific chunks and generating a
    keyphrase from them and then generating queries based on that.

    Attributes
    ----------
    generate_query_prompt : PydanticPrompt
        The prompt used for generating the query.
    """

    name: str = "multi_hop_specific_query_synthesizer"
    theme_persona_matching_prompt: PydanticPrompt = ThemesPersonasMatchingPrompt()
    generate_query_reference_prompt: PydanticPrompt = QueryAnswerGenerationPrompt()

    async def _generate_scenarios(
        self,
        n: int,
        knowledge_graph: KnowledgeGraph,
        persona_list: t.List[Persona],
        callbacks: Callbacks,
    ) -> t.List[MultiHopScenario]:
        """
        Generates a list of scenarios on type MultiHopSpecificQuerySynthesizer
        Steps to generate scenarios:
        1. Filter the knowledge graph to find cluster of nodes or defined relation type. Here entities_overlap
        2. Calculate the number of samples that should be created per cluster to get n samples in total
        3. For each cluster of nodes
            a. Find the entities that are common between the nodes
            b. Find list of personas that can be associated with the entities to create query
            c. Create all possible combinations of (nodes, entities, personas, style, length) as scenarios
            3. Sample num_sample_per_cluster scenarios from the list of scenarios
        4. Return the list of scenarios of length n
        """

        cluster_dict = knowledge_graph.find_direct_clusters(
            relationship_condition=lambda rel: (
                True if rel.type == "entities_overlap" else False
            )
        )

        valid_relationships = [
            rel
            for rel in knowledge_graph.relationships
            if rel.type == "entities_overlap"
        ]

        node_clusters = []
        for key_node, list_of_nodes in cluster_dict.items():
            for node in list_of_nodes:
                node_clusters.append((key_node, node))

        logger.info("found %d clusters", len(cluster_dict))
        scenarios = []
        num_sample_per_cluster = int(np.ceil(n / len(node_clusters)))

        for cluster in node_clusters:
            if len(scenarios) < n:
                key_node, node = cluster
                overlapped_items = []
                for rel in valid_relationships:
                    if rel.source == key_node and rel.target == node:
                        overlapped_items = rel.get_property("overlapped_items")
                        break
                if overlapped_items:
                    themes = list(dict(overlapped_items).keys())
                    prompt_input = ThemesPersonasInput(
                        themes=themes, personas=persona_list
                    )
                    persona_concepts = (
                        await self.theme_persona_matching_prompt.generate(
                            data=prompt_input, llm=self.llm, callbacks=callbacks
                        )
                    )
                    overlapped_items = [list(item) for item in overlapped_items]
                    base_scenarios = self.prepare_combinations(
                        [key_node, node],
                        overlapped_items,
                        PersonaList(personas=persona_list),
                        persona_concepts,
                        property_name="entities",
                    )
                    base_scenarios = self.sample_diverse_combinations(
                        base_scenarios, num_sample_per_cluster
                    )
                    scenarios.extend(base_scenarios)

        return scenarios
