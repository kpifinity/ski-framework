# Contributing to SKI Framework

Thank you for your interest in contributing to the SKI Framework! We welcome contributions from the community.

## Ways to Contribute

### 1. Report Issues or Suggest Improvements
- Found a bug? Open an issue on [GitHub Issues](https://github.com/kpifinity/ski-framework/issues)
- Have an idea? Start a discussion on [GitHub Discussions](https://github.com/kpifinity/ski-framework/discussions)

### 2. Improve Documentation
- Fix typos or clarify confusing sections
- Add examples or use cases
- Improve diagrams or explanations
- Submit a pull request with your improvements

### 3. Develop Tools or Connectors
- Build MCP connectors for new data sources
- Develop tooling for Knowledge Graph extraction or validation
- Create deployment automation scripts
- Contribute reference implementations

### 4. Participate in Community
- Answer questions in [GitHub Discussions](https://github.com/kpifinity/ski-framework/discussions)
- Share your implementation experience
- Contribute sector-specific examples
- Help translate documentation

## Getting Started

### 1. Fork the Repository
```bash
git clone https://github.com/YOUR_USERNAME/ski-framework.git
cd ski-framework
```

### 2. Create a Branch
```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

### 3. Make Your Changes
- Follow the code style guidelines (see below)
- Write clear commit messages
- Test your changes

### 4. Submit a Pull Request
- Push your branch to your fork
- Open a pull request with a clear description
- Link to any related issues

## Code Style Guidelines

### Python
```python
# Follow PEP 8
# Use type hints where possible
# Write docstrings for functions

def extract_knowledge_graph(
    source_documents: List[str],
    llm_model: str = "claude-3"
) -> dict:
    """
    Extract Knowledge Graph from regulatory documents.
    
    Args:
        source_documents: List of document paths
        llm_model: Which LLM to use for extraction
        
    Returns:
        Validated Knowledge Graph dict
    """
    pass
```

### Documentation
- Use clear, plain language
- Include examples where helpful
- Link to relevant sections
- Keep lines under 100 characters where possible

### Commit Messages
```
# Good commit messages follow this format:
# [TYPE] Brief description (50 chars max)
#
# Longer explanation if needed. Explain WHAT and WHY, not HOW.

[docs] Add Knowledge Graph extraction guide
[fix] Correct audit ledger hash chain validation
[feature] Add MCP connector framework
[test] Add integration tests for MiLM deployment
```

## Pull Request Process

1. **Title**: Use format `[TYPE] Brief description`
   - Types: `[docs]`, `[fix]`, `[feature]`, `[test]`, `[refactor]`

2. **Description**: Explain what and why
   - What problem does this solve?
   - How does it solve it?
   - Link to related issues

3. **Testing**: 
   - Include tests for new features
   - Verify existing tests pass
   - Include before/after examples if applicable

4. **Documentation**:
   - Update README if needed
   - Add docstrings for new functions
   - Update relevant docs/

5. **Review**: 
   - Be responsive to feedback
   - Make requested changes promptly
   - Tag maintainers for review

## Development Setup

```bash
# Clone repository
git clone https://github.com/kpifinity/ski-framework.git
cd ski-framework

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements-dev.txt

# Run tests
python -m pytest

# Check code style
flake8 .
black --check .
```

## Licensing

By contributing to SKI Framework, you agree that your contributions will be licensed under its Creative Commons Attribution 4.0 International License.

- Open-source framework and tools: CC BY 4.0
- Pre-built Knowledge Graph libraries: Proprietary (KpiFinity)
- Examples and documentation: CC BY 4.0

## Getting Help

- **Questions about the framework?** Check [SKI Framework documentation](https://skiframework.org)
- **Need implementation help?** Contact [KpiFinity](https://kpifinity.com)
- **Want to discuss ideas?** Start a [GitHub Discussion](https://github.com/kpifinity/ski-framework/discussions)

## Code of Conduct

We're committed to a welcoming and inclusive community.

- Be respectful of others
- Assume good intent
- Welcome new perspectives
- Help each other learn

## Thank You!

We appreciate your contributions to making SKI Framework better. Every contribution—whether code, documentation, or ideas—helps the community.

---

Questions? Open an issue or email hello@kpifinity.com
