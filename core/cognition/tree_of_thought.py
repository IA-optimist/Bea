"""
Tree-of-Thought Reasoning for JarvisMax
Multi-path exploration with pruning and evaluation.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Callable
import structlog

log = structlog.get_logger(__name__)


@dataclass
class ThoughtNode:
    """Single node in thought tree."""
    content: str
    parent: Optional[ThoughtNode] = None
    children: List[ThoughtNode] = None
    score: float = 0.0
    depth: int = 0
    pruned: bool = False
    
    def __post_init__(self):
        if self.children is None:
            self.children = []


class TreeOfThought:
    """
    Tree-of-Thought reasoning engine.
    
    Explores multiple solution paths, evaluates each, prunes low-quality branches.
    Inspired by Yao et al. (2023) "Tree of Thoughts: Deliberate Problem Solving with LLMs"
    """
    
    def __init__(
        self,
        llm_function: Callable,
        max_depth: int = 2,
        branching_factor: int = 3,
        pruning_threshold: float = 0.3,
        mode: str = "bfs"  # bfs, dfs, beam
    ):
        self.llm = llm_function
        self.max_depth = max_depth
        self.branching_factor = branching_factor
        self.pruning_threshold = pruning_threshold
        self.mode = mode
        
    async def solve(self, problem: str) -> dict:
        """
        Solve problem using Tree-of-Thought.
        
        Returns best solution path with confidence score.
        """
        log.info("tot_solving", problem=problem[:100], mode=self.mode)
        
        # Create root node
        root = ThoughtNode(content=f"Problem: {problem}", depth=0)
        
        # Explore tree
        if self.mode == "bfs":
            await self._explore_bfs(root, problem)
        elif self.mode == "dfs":
            await self._explore_dfs(root, problem)
        elif self.mode == "beam":
            await self._explore_beam(root, problem)
        
        # Find best leaf path
        best_path = self._find_best_path(root)
        
        return {
            "solution": best_path[-1].content if best_path else "No solution found",
            "confidence": best_path[-1].score if best_path else 0.0,
            "path": [node.content for node in best_path],
            "nodes_explored": self._count_nodes(root),
            "max_depth_reached": best_path[-1].depth if best_path else 0
        }
    
    async def _explore_bfs(self, root: ThoughtNode, problem: str):
        """Breadth-first exploration."""
        queue = [root]
        
        while queue:
            node = queue.pop(0)
            
            if node.depth >= self.max_depth or node.pruned:
                continue
            
            # Generate child thoughts
            children = await self._generate_children(node, problem)
            node.children = children
            
            # Evaluate and prune
            for child in children:
                child.score = await self._evaluate_thought(child, problem)
                if child.score < self.pruning_threshold:
                    child.pruned = True
                    log.debug("tot_pruned", content=child.content[:50], score=child.score)
                else:
                    queue.append(child)
    
    async def _explore_dfs(self, root: ThoughtNode, problem: str):
        """Depth-first exploration."""
        async def dfs(node: ThoughtNode):
            if node.depth >= self.max_depth or node.pruned:
                return
            
            children = await self._generate_children(node, problem)
            node.children = children
            
            for child in children:
                child.score = await self._evaluate_thought(child, problem)
                if child.score >= self.pruning_threshold:
                    await dfs(child)
                else:
                    child.pruned = True
        
        await dfs(root)
    
    async def _explore_beam(self, root: ThoughtNode, problem: str, beam_width: int = 3):
        """Beam search exploration (keeps top-k nodes at each level)."""
        current_beam = [root]
        
        for depth in range(self.max_depth):
            next_beam = []
            
            for node in current_beam:
                children = await self._generate_children(node, problem)
                node.children = children
                
                for child in children:
                    child.score = await self._evaluate_thought(child, problem)
                    next_beam.append(child)
            
            # Keep top beam_width nodes
            next_beam.sort(key=lambda n: n.score, reverse=True)
            current_beam = next_beam[:beam_width]
            
            # Prune low-scoring nodes
            for node in next_beam[beam_width:]:
                node.pruned = True
    
    async def _generate_children(self, node: ThoughtNode, problem: str) -> List[ThoughtNode]:
        """Generate child thought nodes."""
        prompt = f"""Given this problem and current thought, generate {self.branching_factor} distinct next steps.

Problem: {problem}

Current thought: {node.content}

Generate {self.branching_factor} different approaches to continue. Be concise (1-2 sentences each).
Format as numbered list:
1. [approach 1]
2. [approach 2]
3. [approach 3]"""
        
        try:
            response = await self.llm(prompt)
            
            # Parse numbered list
            lines = [l.strip() for l in response.split("\n") if l.strip()]
            thoughts = []
            
            for line in lines:
                if line[0].isdigit() and "." in line[:3]:
                    content = line.split(".", 1)[1].strip()
                    thoughts.append(content)
            
            # Create child nodes
            children = []
            for i, thought in enumerate(thoughts[:self.branching_factor]):
                child = ThoughtNode(
                    content=thought,
                    parent=node,
                    depth=node.depth + 1
                )
                children.append(child)
            
            log.debug("tot_children_generated", count=len(children), depth=node.depth + 1)
            return children
            
        except Exception as e:
            log.error("tot_generation_failed", error=str(e))
            return []
    
    async def _evaluate_thought(self, node: ThoughtNode, problem: str) -> float:
        """Evaluate thought quality (0.0 to 1.0)."""
        prompt = f"""Evaluate this reasoning step for solving the problem.

Problem: {problem}

Reasoning step: {node.content}

Rate the quality of this step on a scale of 0.0 to 1.0, where:
- 1.0 = Excellent, directly advances toward solution
- 0.5 = Acceptable, somewhat relevant
- 0.0 = Poor, off-track or incorrect

Respond with ONLY a number between 0.0 and 1.0."""
        
        try:
            response = await self.llm(prompt)
            score = float(response.strip())
            return max(0.0, min(1.0, score))
        except Exception:
            return 0.5  # Default neutral score
    
    def _find_best_path(self, root: ThoughtNode) -> List[ThoughtNode]:
        """Find highest-scoring path from root to leaf."""
        best_path = []
        best_score = -1.0
        
        def dfs(node: ThoughtNode, path: List[ThoughtNode]):
            nonlocal best_path, best_score
            
            current_path = path + [node]
            
            if not node.children or node.pruned:
                # Leaf node - evaluate path
                avg_score = sum(n.score for n in current_path) / len(current_path)
                if avg_score > best_score:
                    best_score = avg_score
                    best_path = current_path
            else:
                for child in node.children:
                    if not child.pruned:
                        dfs(child, current_path)
        
        dfs(root, [])
        return best_path
    
    def _count_nodes(self, root: ThoughtNode) -> int:
        """Count total nodes in tree."""
        count = 1
        for child in root.children:
            count += self._count_nodes(child)
        return count
