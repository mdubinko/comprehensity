from __future__ import annotations

"""
Source code graph data structures and interfaces.

This module provides the core data structures for representing codebases
as in-memory graphs with files, directories, and their relationships.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union, Self


@dataclass
class FileNode:
    """Represents a file in the codebase with extensible metadata"""
    path: str
    size_bytes: int
    extension: str
    imports: Set[str] = field(default_factory=set)
    imported_by: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class DirectoryNode:
    """Represents a directory in the codebase"""
    path: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class SourceGraph:
    """
    In-memory representation of a source code codebase.
    
    Provides interfaces to construct, augment, and read from the graph
    while maintaining flexibility for future extensions.
    """
    
    def __init__(self, root_path: str = ""):
        self.root_path = root_path
        self._files: Dict[str, FileNode] = {}
        self._directories: Dict[str, DirectoryNode] = {}
        self.metadata: Dict[str, Any] = {}
    
    # Construction Interface
    def add_file(self, path: str, size_bytes: int, extension: str = None) -> FileNode:
        """Add a file to the graph"""
        if extension is None:
            extension = Path(path).suffix.lower() if '.' in Path(path).name else ''
        
        node = FileNode(path=path, size_bytes=size_bytes, extension=extension)
        self._files[path] = node
        return node
    
    def add_directory(self, path: str) -> DirectoryNode:
        """Add a directory to the graph"""
        node = DirectoryNode(path=path)
        self._directories[path] = node
        return node
    
    def remove_file(self, path: str) -> bool:
        """Remove a file from the graph. Returns True if removed, False if not found."""
        return self._files.pop(path, None) is not None
    
    def remove_directory(self, path: str) -> bool:
        """Remove a directory from the graph. Returns True if removed, False if not found."""
        return self._directories.pop(path, None) is not None
    
    # Augmentation Interface
    def add_import(self, from_file: str, to_file: str) -> None:
        """Add an import relationship between files"""
        if from_file in self._files:
            self._files[from_file].imports.add(to_file)
        if to_file in self._files:
            self._files[to_file].imported_by.add(from_file)
    
    def add_file_metadata(self, path: str, key: str, value: Any) -> bool:
        """Add metadata to a file. Returns True if file exists, False otherwise."""
        if path in self._files:
            self._files[path].metadata[key] = value
            return True
        return False
    
    def add_directory_metadata(self, path: str, key: str, value: Any) -> bool:
        """Add metadata to a directory. Returns True if directory exists, False otherwise."""
        if path in self._directories:
            self._directories[path].metadata[key] = value
            return True
        return False
    
    def set_graph_metadata(self, key: str, value: Any) -> None:
        """Set graph-level metadata"""
        self.metadata[key] = value
    
    # Read Interface
    def get_file(self, path: str) -> Optional[FileNode]:
        """Get a file node by path"""
        return self._files.get(path)
    
    def get_directory(self, path: str) -> Optional[DirectoryNode]:
        """Get a directory node by path"""
        return self._directories.get(path)
    
    def get_all_files(self) -> List[FileNode]:
        """Get all file nodes"""
        return list(self._files.values())
    
    def get_all_directories(self) -> List[DirectoryNode]:
        """Get all directory nodes"""
        return list(self._directories.values())
    
    def get_files_by_extension(self, extension: str) -> List[FileNode]:
        """Get all files with a specific extension"""
        return [f for f in self._files.values() if f.extension == extension]
    
    def get_files_by_pattern(self, pattern: str) -> List[FileNode]:
        """Get files matching a pattern (simple glob-like matching)"""
        import fnmatch
        return [f for f in self._files.values() if fnmatch.fnmatch(f.path, pattern)]
    
    def has_file(self, path: str) -> bool:
        """Check if a file exists in the graph"""
        return path in self._files
    
    def has_directory(self, path: str) -> bool:
        """Check if a directory exists in the graph"""
        return path in self._directories
    
    def file_count(self) -> int:
        """Get total number of files"""
        return len(self._files)
    
    def directory_count(self) -> int:
        """Get total number of directories"""
        return len(self._directories)
    
    def total_size_bytes(self) -> int:
        """Get total size of all files in bytes"""
        return sum(f.size_bytes for f in self._files.values())
    
    # Serialization Interface (preserving existing formats for compatibility)
    def to_pipe_format(self) -> List[str]:
        """Serialize to original pipe-delimited format for backwards compatibility"""
        lines = []
        
        # Add files
        for file_node in self._files.values():
            line = f"{file_node.path}|{file_node.size_bytes}|false"
            lines.append(line)
        
        # Add directories
        for dir_node in self._directories.values():
            line = f"{dir_node.path}|0|true"
            lines.append(line)
        
        return sorted(lines)
    
    def to_csv_format(self) -> str:
        """Serialize to CSV format"""
        output = []
        output.append("path,type,size_bytes,extension")
        
        # Add files
        for file_node in sorted(self._files.values(), key=lambda x: x.path):
            output.append(f"{file_node.path},file,{file_node.size_bytes},{file_node.extension}")
        
        # Add directories
        for dir_node in sorted(self._directories.values(), key=lambda x: x.path):
            output.append(f"{dir_node.path},directory,0,")
        
        return '\n'.join(output)
    
    def to_json_format(self, include_metadata: bool = False) -> str:
        """Serialize to JSON format"""
        files_data = []
        for f in sorted(self._files.values(), key=lambda x: x.path):
            file_data = {
                "path": f.path,
                "size_bytes": f.size_bytes,
                "extension": f.extension
            }
            
            # Add import information if available
            if f.imports:
                file_data["imports"] = sorted(list(f.imports))
            if f.imported_by:
                file_data["imported_by"] = sorted(list(f.imported_by))
            if 'import_details' in f.metadata:
                file_data["import_details"] = f.metadata['import_details']
            
            # Add metadata if requested
            if include_metadata and f.metadata:
                file_data["metadata"] = f.metadata
                
            files_data.append(file_data)
        
        dirs_data = []
        for d in sorted(self._directories.values(), key=lambda x: x.path):
            dir_data = {"path": d.path}
            # Add metadata if requested
            if include_metadata and d.metadata:
                dir_data["metadata"] = d.metadata
            dirs_data.append(dir_data)
        
        data = {
            "root_path": self.root_path,
            "files": files_data,
            "directories": dirs_data
        }
        
        # Add graph-level metadata if requested
        if include_metadata and self.metadata:
            data["metadata"] = self.metadata
        
        return json.dumps(data, indent=2)
    
    def to_dict(self, include_metadata: bool = False) -> Dict:
        """Convert to dictionary representation"""
        return json.loads(self.to_json_format(include_metadata=include_metadata))


