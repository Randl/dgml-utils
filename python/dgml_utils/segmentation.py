from lxml import etree
from typing import List, Optional

from dgml_utils.config import (
    DEFAULT_XML_MODE,
    DEFAULT_MIN_TEXT_LENGTH,
    DEFAULT_SUBCHUNK_TABLES,
    DEFAULT_WHITESPACE_NORMALIZE_TEXT,
    DEFAULT_PARENT_HIERARCHY_LEVELS,
    DEFAULT_MAX_TEXT_LENGTH,
    STRUCTURE_KEY,
    TABLE_NAME,
)
from dgml_utils.conversions import (
    clean_tag,
    simplified_xml,
    text_node_to_text,
    xhtml_table_to_text,
    xml_nth_ancestor,
)
from dgml_utils.locators import xpath
from dgml_utils.models import Chunk


def is_descendant_of_structural(node) -> bool:
    """True if node is a descendant of a node with the structure attribute set."""
    for ancestor in node.iterancestors():
        if STRUCTURE_KEY in ancestor.attrib:
            return True
    return False


def is_structural(node) -> bool:
    """True if node itself has the structure attribute set."""
    return node is not None and STRUCTURE_KEY in node.attrib


def has_structural_children(node) -> bool:
    """True if node has any descendents (at any depth) with the structure attribute set."""
    return len(node.findall(f".//*[@{STRUCTURE_KEY}]")) > 0


def is_force_prepend_chunk(node) -> bool:
    return node is not None and node.attrib.get(STRUCTURE_KEY) in ["lim"]


def get_chunks(
    node,
    min_text_length=DEFAULT_MIN_TEXT_LENGTH,
    max_text_length=DEFAULT_MAX_TEXT_LENGTH,
    whitespace_normalize_text=DEFAULT_WHITESPACE_NORMALIZE_TEXT,
    sub_chunk_tables=DEFAULT_SUBCHUNK_TABLES,
    xml_mode=DEFAULT_XML_MODE,
    parent_hierarchy_levels=DEFAULT_PARENT_HIERARCHY_LEVELS,
) -> List[Chunk]:
    """Returns all structural chunks in the given node, as xml chunks."""
    final_chunks: List[Chunk] = []
    prepended_small_chunk: Optional[Chunk] = None

    def _build_chunks(
        node,
        xml_mode=DEFAULT_XML_MODE,
        max_text_length=DEFAULT_MAX_TEXT_LENGTH,
        whitespace_normalize_text=DEFAULT_WHITESPACE_NORMALIZE_TEXT,
    ) -> List[Chunk]:
        """
        Builds chunks from the given node, splitting on the given max length to ensure
        all the returned chunks as less than the given max length.
        """
        if xml_mode:
            node_text = simplified_xml(
                node,
                whitespace_normalize_text=whitespace_normalize_text,
            )
        elif node.tag == TABLE_NAME:
            node_text = xhtml_table_to_text(node, whitespace_normalize=whitespace_normalize_text)
        else:
            node_text = text_node_to_text(node, whitespace_normalize=whitespace_normalize_text)

        node_text_splits = [node_text[i : i + max_text_length] for i in range(0, len(node_text), max_text_length)]

        chunks = []
        for text in node_text_splits:
            chunks.append(
                Chunk(
                    tag=clean_tag(node),
                    text=text,
                    xml=etree.tostring(node, encoding="unicode"),
                    structure=node.attrib.get(STRUCTURE_KEY) or "",
                    xpath=xpath(node),
                )
            )
        return chunks

    def _traverse(node):
        nonlocal prepended_small_chunk  # Access the variable from the outer scope

        is_table_leaf_node = node.tag == TABLE_NAME and not sub_chunk_tables
        is_text_leaf_node = is_structural(node) and not has_structural_children(node)
        is_structure_orphaned_node = is_descendant_of_structural(node) and not has_structural_children(node)

        if is_table_leaf_node or is_text_leaf_node or is_structure_orphaned_node:
            sub_chunks: List[Chunk] = _build_chunks(
                node,
                xml_mode=xml_mode,
                max_text_length=max_text_length,
                whitespace_normalize_text=whitespace_normalize_text,
            )
            ancestor_chunk = None
            if xml_mode and parent_hierarchy_levels > 0:
                # For xml chunks, use tree hierarchy directly on the node
                # For text chunks use flat window of before/after chunks
                # (below once all chunks are calculated, so no parent set here.)
                ancestor_node = xml_nth_ancestor(
                    node,
                    n=parent_hierarchy_levels,
                    max_text_length=max_text_length,
                    whitespace_normalize_text=whitespace_normalize_text,
                )

                # We split the current chunk into sub-chunks if longer than max length,
                # to avoid loss of text. However, if the ancestor is longer than max length
                # what do we do? For now let's just pick the first ancestor but this could
                # be lossy if the caller is only using ancestors.
                ancestor_chunk = _build_chunks(
                    ancestor_node,
                    xml_mode=xml_mode,
                    max_text_length=max_text_length,
                    whitespace_normalize_text=whitespace_normalize_text,
                )[0]

            for chunk in sub_chunks:
                chunk.parent = ancestor_chunk

                if prepended_small_chunk and sub_chunks:
                    chunk = prepended_small_chunk + chunk
                    prepended_small_chunk = None  # clear

                if len(chunk.text) < min_text_length or is_force_prepend_chunk(node):
                    # Prepend small chunks or list item markers to the following chunk
                    prepended_small_chunk = chunk
                else:
                    final_chunks.append(chunk)
        else:
            # Continue deeper in the tree
            for child in node:
                _traverse(child)

    _traverse(node)

    # Append any remaining prepended_small_chunk that wasn't followed by a large chunk
    if prepended_small_chunk:
        final_chunks.append(prepended_small_chunk)

    if not xml_mode and parent_hierarchy_levels > 0:
        # Set parents for text chunks using flat window of before/after chunks
        ...

    return final_chunks


def get_chunks_str(
    dgml: str,
    min_text_length=DEFAULT_MIN_TEXT_LENGTH,
    max_text_length=DEFAULT_MAX_TEXT_LENGTH,
    whitespace_normalize_text=DEFAULT_WHITESPACE_NORMALIZE_TEXT,
    sub_chunk_tables=DEFAULT_SUBCHUNK_TABLES,
    xml_mode=DEFAULT_XML_MODE,
    parent_hierarchy_levels=DEFAULT_PARENT_HIERARCHY_LEVELS,
) -> List[Chunk]:
    root = etree.fromstring(dgml)

    return get_chunks(
        node=root,
        min_text_length=min_text_length,
        max_text_length=max_text_length,
        whitespace_normalize_text=whitespace_normalize_text,
        sub_chunk_tables=sub_chunk_tables,
        xml_mode=xml_mode,
        parent_hierarchy_levels=parent_hierarchy_levels,
    )
