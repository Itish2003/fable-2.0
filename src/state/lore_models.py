import os
from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector

Base = declarative_base()

class LoreNode(Base):
    __tablename__ = 'lore_nodes'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, unique=True, nullable=False)
    node_type = Column(String, index=True, nullable=False) # 'character', 'location', 'faction', 'event'
    attributes = Column(JSON, default={}) # Flexible storage for node-specific data

    embeddings = relationship("LoreEmbedding", back_populates="node", cascade="all, delete-orphan")
    
    # Relationships for NetworkX reconstruction
    edges_out = relationship("LoreEdge", foreign_keys="[LoreEdge.source_id]", back_populates="source")
    edges_in = relationship("LoreEdge", foreign_keys="[LoreEdge.target_id]", back_populates="target")

class LoreEdge(Base):
    __tablename__ = 'lore_edges'

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey('lore_nodes.id'), nullable=False)
    target_id = Column(Integer, ForeignKey('lore_nodes.id'), nullable=False)
    relationship_type = Column(String, nullable=False) # e.g., 'allied_with', 'located_in'
    
    # Epistemic Filtering: Who is allowed to know about this connection?
    # If empty, it's public knowledge. If populated, only these characters (by name/id) can traverse this edge.
    visibility_whitelist = Column(JSON, default=[]) 

    source = relationship("LoreNode", foreign_keys=[source_id], back_populates="edges_out")
    target = relationship("LoreNode", foreign_keys=[target_id], back_populates="edges_in")

class LoreEmbedding(Base):
    __tablename__ = 'lore_embeddings'

    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(Integer, ForeignKey('lore_nodes.id'), nullable=True) # Can be null if it's general world context
    
    universe = Column(String, index=True)
    volume = Column(String, index=True)
    chunk_text = Column(Text, nullable=False)
    
    # nomic-embed-text:v1.5 produces 768-dimensional vectors.
    embedding = Column(Vector(768), nullable=False) 

    node = relationship("LoreNode", back_populates="embeddings")

class SourceText(Base):
    __tablename__ = 'source_text'

    id = Column(Integer, primary_key=True, index=True)
    universe = Column(String, index=True)
    volume = Column(String, index=True)
    content = Column(Text, nullable=False)
    word_count = Column(Integer, default=0)

