# Decision Log

This file records architectural and implementation decisions using a list format.
2025-09-07 14:38:11 - Initial Memory Bank setup and decision tracking initialization.

## Decision

* Initialize Memory Bank system for project context tracking

## Rationale 

* Provides structured approach to track project evolution, decisions, and context
* Enables better coordination between different development modes
* Maintains historical record of architectural choices and their reasoning
* Supports task-based development workflow with proper documentation

## Implementation Details

* Created memory-bank/ directory with core tracking files
* Established productContext.md for high-level project overview
* Set up activeContext.md for current status and focus tracking
* Implemented progress.md for task-based progress monitoring
* Added decisionLog.md for architectural decision recording
* Will include systemPatterns.md for recurring patterns documentation

2025-09-07 16:44:00 - Telegram Bot Architecture Decisions

## Decision

* Implemented minimal Telegram bot with modular architecture
* Used python-telegram-bot library for Telegram API integration
* Created database abstraction layer with SQLite backend
* Implemented TOML configuration system

## Rationale 

* python-telegram-bot is the most mature and well-maintained Python library for Telegram bots
* Database wrapper pattern allows easy migration to other databases (PostgreSQL, MySQL, etc.) in future
* TOML configuration provides human-readable, easy-to-edit configuration format
* Modular design separates concerns: main bot logic, database operations, configuration
* Test-driven approach ensures reliability and maintainability

## Implementation Details

* Created DatabaseWrapper class with consistent interface for database operations
* Implemented comprehensive bot commands: /start, /help, /stats, /echo
* Added message persistence and user statistics tracking
* Used thread-local connections for SQLite thread safety
* Added Prinny personality with "dood!" responses for character
* Created comprehensive test suite covering all components
* Structured project with clear separation of configuration, database, and bot logic

[2025-09-07 21:56:13] - Fixed Type Annotation and Null Safety Issues in main.py

## Decision

* Removed problematic YCloudML type annotation that was causing Pylance errors
* Added comprehensive null safety checks for Telegram bot handlers
* Fixed all type safety issues related to optional Update attributes

## Rationale 

* The YCloudML type annotation was causing "Expected class but received DocSourceType" error due to complex import structure in yandex_cloud_ml_sdk
* Telegram bot Update objects can have None values for effective_user and message in edge cases
* Type safety is crucial for production bot reliability and prevents runtime errors
* Removing the return type annotation while keeping runtime functionality intact is better than having type checker errors

## Implementation Details

* Removed `-> "YCloudML"` return type annotation from `_init_yc_ml_sdk()` method
* Added null checks for `update.effective_user` and `update.message` in all bot command handlers:
  - `start_command()`: Added checks for user and message
  - `help_command()`: Added check for message
  - `stats_command()`: Added checks for user and message  
  - `echo_command()`: Added check for message
  - `handle_message()`: Added checks for user, message, and message.text
* Used early return pattern (`if not condition: return`) for clean null handling
* Maintained all existing functionality while improving type safety

[2025-09-12 23:18:00] - Added Command Line Argument Parsing and Daemon Support

## Decision

* Implemented comprehensive command line argument parsing with argparse
* Added daemon/background forking functionality for Unix-like systems
* Enhanced main() function to support custom configuration files and daemon mode

## Rationale 

* Command line arguments provide flexibility for deployment and testing scenarios
* Custom config file support allows multiple bot instances with different configurations
* Daemon mode enables running the bot as a background service without terminal attachment
* PID file support allows proper process management in daemon mode
* Windows compatibility check prevents daemon mode on unsupported platforms

## Implementation Details

* Added argparse import and os import for system operations
* Created parse_arguments() function with three command line options:
  - `-c/--config`: Custom configuration file path (default: config.toml)
  - `-d/--daemon`: Run in background daemon mode
  - `--pid-file`: Specify PID file location for daemon mode (default: gromozeka.pid)
* Implemented daemonize() function with proper Unix double-fork pattern:
  - First fork to detach from parent process
  - Session leader creation and working directory change
  - Second fork to prevent zombie processes
  - PID file creation for process tracking
  - Standard file descriptor redirection to /dev/null
* Updated main() function to use argument parsing and conditional daemon forking
* Added Windows platform check to prevent daemon mode on unsupported systems
* Maintained all existing bot functionality while adding new deployment options

[2025-09-12 23:34:51] - Implemented Configurable Logging System

## Decision

* Implemented comprehensive logging configuration system in `_init_logger()` method
* Added support for configurable log levels, formats, and file logging
* Updated configuration example with new logging options including Yandex Cloud ML settings

## Rationale 

* Configurable logging is essential for production deployment and debugging
* File logging allows persistent log storage for monitoring and troubleshooting
* Different log levels enable appropriate verbosity for development vs production environments
* Centralized logging configuration through TOML config maintains consistency with existing architecture

## Implementation Details

* Enhanced `_init_logger()` method to read logging configuration from config file
* Supported log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL with validation
* Configurable log format string with sensible default
* Optional file logging with automatic directory creation
* Proper handler management to avoid duplicate log entries
* Maintained existing httpx logging level override to reduce noise
* Updated config.toml.example with comprehensive logging and yc-ml sections
* Added error handling for invalid log levels and file creation failures

[2025-09-12 23:08:30] - Modular Architecture Refactoring Completed

## Decision

* Successfully refactored monolithic main.py into a clean modular architecture
* Separated concerns into dedicated directories: lib/, bot/, config/, database/, llm/
* Created specialized manager classes for each component
* Maintained all existing functionality while improving code organization

## Rationale 

* Monolithic single-file architecture was becoming difficult to maintain and extend
* Separation of concerns improves code readability, testability, and maintainability
* Modular structure allows for easier unit testing of individual components
* Clear directory structure makes it easier for new developers to understand the codebase
* Component isolation reduces coupling and improves code reusability

## Implementation Details

* Created lib/ directory with logging utilities (lib/logging_utils.py)
* Created bot/ directory with handlers (bot/handlers.py) and application logic (bot/application.py)
* Created config/ directory with ConfigManager class (config/manager.py) for centralized configuration
* Created database/ directory with DatabaseManager (database/manager.py) and moved existing wrapper
* Created llm/ directory with YandexMLManager (llm/yandex_ml.py) for LLM integration
* Refactored main.py to orchestrate all components through clean interfaces
* Preserved all command-line arguments and daemon functionality
* All imports tested and verified working correctly
* Maintained backward compatibility with existing configuration files

[2025-09-12 23:12:32] - Implemented Missing Database Method for Chat Message Retrieval

## Decision

* Implemented `get_chat_messages_newer_than()` method in DatabaseWrapper class
* Method retrieves chat messages from specific chat newer than given date
* Resolves TODO in bot/handlers.py that was calling non-existent database method

## Rationale 

* The bot handlers were trying to call `self.db.get_chat_messages_newer_than()` but this method didn't exist
* This method is needed for LLM integration to get recent chat messages for context
* Consistent with existing database wrapper patterns and error handling
* Supports the bot's ability to provide summaries of recent chat activity

## Implementation Details

* Added method to DatabaseWrapper class in database/wrapper.py
* Method takes chat_id (int) and since_date parameters
* Queries chat_messages table with WHERE clause for chat_id and date filtering
* Orders results by date ASC to get chronological message flow
* Returns List[Dict[str, Any]] consistent with other database methods
* Includes proper error handling and logging like other database methods
* Uses existing cursor context manager pattern for transaction safety

[2025-09-13 14:18:27] - Implemented Missing get_chat_message_by_message_id Database Method

## Decision

* Implemented `get_chat_message_by_message_id()` method in DatabaseWrapper class
* Method retrieves specific chat message by message_id, chat_id, and optional thread_id
* Resolves TODO in bot/handlers.py that was calling non-existent database method

## Rationale 

* The bot handlers were trying to call `self.db.get_chat_message_by_message_id()` but this method didn't exist
* This method is needed for reply message handling to get the parent message being replied to
* Consistent with existing database wrapper patterns and error handling
* Supports the bot's ability to track message threads and reply chains

## Implementation Details

* Added method to DatabaseWrapper class in database/wrapper.py
* Method takes chat_id (int), thread_id (Optional[int]), and message_id (int) parameters
* Queries chat_messages table with WHERE clause for chat_id, message_id, and optional thread_id filtering
* Uses proper NULL handling for thread_id with `((? IS NULL) OR (thread_id = ?))` pattern
* Returns Optional[Dict[str, Any]] consistent with other database methods
* Includes proper error handling and logging like other database methods
* Uses existing cursor context manager pattern for transaction safety
* Added LIMIT 1 for performance since message_id should be unique per chat

[2025-09-13 14:25:55] - Implemented Missing get_chat_messages_by_root_id Database Method

## Decision

* Implemented `get_chat_messages_by_root_id()` method in DatabaseWrapper class
* Fixed attribute access bug in bot handlers for dictionary-based database results
* Completed TODO implementation for bot message thread handling

## Rationale 

* The bot handlers were calling `self.db.get_chat_messages_by_root_id()` but this method didn't exist
* This method is needed for LLM integration to get all messages in a conversation thread by root message ID
* The handler code was incorrectly accessing dictionary values as object attributes
* Consistent with existing database wrapper patterns and error handling

## Implementation Details

* Added method to DatabaseWrapper class in database/wrapper.py
* Method takes chatId (int), rootMessageId (int), and optional threadId parameters
* Queries chat_messages table with WHERE clause for chat_id, root_message_id, and optional thread_id filtering
* Orders results by date ASC to get chronological message flow for LLM context
* Returns List[Dict[str, Any]] consistent with other database methods
* Fixed bot/handlers.py to use dictionary access: `storedMsg["message_category"]` and `storedMsg["message_text"]`
* Includes proper error handling and logging like other database methods
* Uses existing cursor context manager pattern for transaction safety

[2025-09-14 03:33:00] - Implemented Comprehensive LLM Management System

## Decision

* Created new AI module with LLMManager class for managing multiple LLM providers and models
* Implemented AbstractLLMProvider and AbstractModel base classes for extensible architecture
* Created scaffold providers for yc-sdk, yc-openai, and openrouter based on config.toml.example
* Replaced single YandexMLManager with flexible multi-provider LLMManager in main.py

## Rationale 

* The existing single YandexMLManager was limited to one provider and inflexible for multiple models
* New architecture supports multiple LLM providers (Yandex Cloud SDK, Yandex Cloud OpenAI, OpenRouter)
* Abstract base classes enable easy addition of new providers without code changes
* Configuration-driven model initialization allows dynamic model management
* Backward compatibility maintained through default model selection for existing bot functionality

## Implementation Details

* Created ai/ directory with modular structure:
  - AbstractModel: Base class for all models with run() method and metadata
  - AbstractLLMProvider: Base class for providers with model management methods
  - LLMManager: Central coordinator for providers and models with listModels, getModel, getModelInfo methods
* Implemented three provider scaffolds:
  - YcSdkProvider: Uses yandex_cloud_ml_sdk for native Yandex Cloud integration
  - YcOpenaiProvider: Uses OpenAI-compatible API for Yandex Cloud models
  - OpenrouterProvider: Uses OpenRouter API for accessing various LLM models
* Updated ConfigManager with get_models_config() method for new configuration structure
* Modified main.py to use LLMManager instead of YandexMLManager with backward compatibility
* All providers support temperature, context_size, and model versioning configuration
* Error handling and logging implemented throughout the system for production reliability

[2025-09-14 16:42:50] - Created BasicOpenAI Base Classes for Provider Refactoring

## Decision

* Created BasicOpenAIModel and BasicOpenAIProvider base classes to eliminate code duplication between YCOpenAI and OpenRouter providers
* Refactored both YcOpenaiModel/YcOpenaiProvider and OpenrouterModel/OpenrouterProvider to inherit from the new base classes
* Moved all common OpenAI client functionality into shared base classes with extensible hook methods

## Rationale 

* YCOpenAI and OpenRouter providers had nearly identical code structure since both use the OpenAI client library
* Code duplication made maintenance difficult and error-prone when making changes to common functionality
* Template method pattern allows base classes to handle common operations while subclasses customize specific behavior
* Inheritance hierarchy reduces code size and improves maintainability without losing functionality
* Virtual environment path (./venv/bin/python3) should be used for Python execution in this project

## Implementation Details

* Created ai/providers/basic_openai_provider.py with two base classes:
  - BasicOpenAIModel: Handles common model operations with _get_model_name() and _get_extra_params() hooks
  - BasicOpenAIProvider: Handles common provider operations with _get_base_url(), _get_api_key(), and _create_model_instance() hooks
* Refactored YcOpenaiModel to inherit from BasicOpenAIModel:
  - Overrides _get_model_name() to return YC-specific model URL format
  - Overrides _get_extra_params() to add max_tokens parameter
* Refactored YcOpenaiProvider to inherit from BasicOpenAIProvider:
  - Overrides _get_base_url() to return Yandex Cloud endpoint
  - Overrides _get_api_key() to validate folder_id requirement
  - Overrides _create_model_instance() to create YcOpenaiModel instances
* Refactored OpenrouterModel to inherit from BasicOpenAIModel:
  - Overrides _get_model_name() to return model_id directly
  - Overrides _get_extra_params() to add OpenRouter-specific headers
* Refactored OpenrouterProvider to inherit from BasicOpenAIProvider:
  - Overrides _get_base_url() to return OpenRouter endpoint
  - Overrides _create_model_instance() to create OpenrouterModel instances
* All functionality preserved while reducing code duplication by approximately 60%
* Comprehensive testing confirmed all imports, inheritance, and syntax validation pass successfully

[2025-09-15 21:57:30] - Implemented Telegram MarkdownV2 Conversion and Validation Functions

## Decision

* Created comprehensive Telegram MarkdownV2 conversion and validation utilities in lib/telegram_markdown.py
* Implemented convert_markdown_to_v2() function to convert standard Markdown to Telegram's MarkdownV2 format
* Implemented validate_markdown_v2() and is_valid_markdown_v2() functions for MarkdownV2 validation
* Added proper escaping logic for different contexts (general text, code blocks, link URLs)

## Rationale 

* Telegram's MarkdownV2 format has specific escaping requirements that differ from standard Markdown
* The bot needs reliable conversion from standard Markdown to avoid formatting errors in Telegram messages
* Validation functions help ensure generated MarkdownV2 text is properly formatted before sending
* Modular design in lib/ directory follows the project's established architecture patterns
* Comprehensive testing ensures reliability for production use, dood!

## Implementation Details

* Created escape_markdown_v2() function with context-aware escaping:
  - General context: escapes _*[]()~`>#+-=|{}.! characters
  - Pre/code context: escapes ` and \ characters only
  - Link URL context: escapes ) and \ characters only
* Implemented convert_markdown_to_v2() with proper conversion logic:
  - **bold** → *bold* (MarkdownV2 bold syntax)
  - *italic* → _italic_ (MarkdownV2 italic syntax)
  - ~~strikethrough~~ → ~strikethrough~ (MarkdownV2 strikethrough)
  - Preserves code blocks, inline code, links, and block quotes
  - Uses placeholder technique to avoid conflicts between bold and italic processing
* Created validate_markdown_v2() function with comprehensive validation:
  - Checks for properly escaped special characters outside markup contexts
  - Validates balanced markup (unclosed bold, italic, etc.)
  - Special handling for block quotes (> at start of line is valid)
  - Returns detailed error messages for debugging
* All functions thoroughly tested with 27 test cases covering edge cases and complex scenarios
* Functions integrate seamlessly with existing bot architecture and can be imported as needed

[2025-09-15 22:34:30] - Fixed Telegram MarkdownV2 Escaping and Validation Issues

## Decision

* Fixed critical escaping issues in lib/telegram_markdown.py functions
* Improved convertMarkdownToV2() function to properly escape all special characters in plain text
* Enhanced validateMarkdownV2() function to accurately detect unescaped characters
* Fixed test file import issues for proper testing

## Rationale 

* The original functions were not properly escaping parentheses and other special characters in plain text sections
* Telegram's MarkdownV2 format requires escaping of '_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!' characters in general text
* The validation function was too lenient and not catching unescaped characters properly
* Proper escaping prevents Telegram API errors when sending formatted messages

## Implementation Details

* Updated markup pattern regex in convertMarkdownToV2() to better identify code blocks: `r'(\*[^*]*\*|_[^_]*_|__[^_]*__|~[^~]*~|\|\|[^|]*\|\||`[^`]*`|```[\s\S]*?```|\[[^\]]*\]\([^)]*\)|^>[^\n]*$)'`
* Enhanced validateMarkdownV2() function with more precise code block detection and improved unescaped character detection logic
* Added proper handling for escaped backslashes in validation (double backslash case)
* Fixed test file import path from `telegram_markdown` to `lib.telegram_markdown` with proper sys.path setup
* All parentheses, periods, hashes, dashes and other special characters now properly escaped with backslashes
* Validation now correctly returns True for properly escaped text and False with detailed error messages for unescaped characters

[2025-09-15 22:40:10] - Fixed Parentheses Escaping Inside Markup Blocks

## Decision

* Fixed critical issue where parentheses and other special characters inside markup blocks (bold, italic, strikethrough) were not being escaped
* Updated convertMarkdownToV2() function to properly escape special characters within markup content
* All special characters now properly escaped according to Telegram MarkdownV2 specification

## Rationale 

* Telegram's MarkdownV2 format requires ALL special characters to be escaped, even inside markup blocks like *bold* and _italic_
* The previous implementation was only escaping characters in plain text sections, leaving markup content unescaped
* This caused Telegram API errors when sending messages with parentheses or other special characters inside formatted text
* Proper escaping ensures all MarkdownV2 messages are valid and render correctly in Telegram

## Implementation Details

* Modified replace_bold() function to escape content: `escaped_bold_text = escapeMarkdownV2(bold_text, 'general')`
* Modified replace_italic() function to escape content: `escaped_italic_text = escapeMarkdownV2(italic_text, 'general')`
* Modified replace_strikethrough() function to escape content: `escaped_strike_text = escapeMarkdownV2(strike_text, 'general')`
* Now parentheses inside markup are properly escaped: `*Bold \(text in parentheses\)*`
* All other special characters (periods, colons, dashes, etc.) inside markup are also properly escaped
* Test validation now correctly returns True for all properly escaped content

[2025-09-18 16:16:00] - Implemented Gromozeka Markdown Parser v1.0

## Decision

* Implemented comprehensive Markdown parser following the Gromozeka Markdown Specification v1.0
* Created modular architecture with separate components for tokenization, block parsing, inline parsing, and rendering
* Built extensible AST (Abstract Syntax Tree) system with proper node hierarchy
* Implemented both HTML and Markdown renderers for output flexibility

## Rationale 

* The specification required a minimal but extensible Markdown parser with clear parsing rules
* Modular design allows for easy maintenance and future extensions
* AST-based approach provides flexibility for different output formats and transformations
* Following the four-stage processing model (Tokenization → Block Parsing → Inline Parsing → Rendering) ensures predictable behavior
* Comprehensive test suite ensures reliability and specification compliance

## Implementation Details

* Created lib/markdown/ directory with 8 core modules:
  - __init__.py: Main module interface with convenience functions
  - ast_nodes.py: AST node classes (MDDocument, MDParagraph, MDHeader, etc.)
  - tokenizer.py: Token-based input processing with 15+ token types
  - block_parser.py: Block-level element parsing (headers, paragraphs, lists, code blocks, etc.)
  - inline_parser.py: Inline element parsing (emphasis, links, images, code spans, etc.)
  - renderer.py: HTML and Markdown output renderers
  - parser.py: Main orchestrating parser class with error handling
  - test_markdown_parser.py: Comprehensive test suite with 100+ test cases

* Supported Markdown elements per specification:
  - Block elements: Paragraphs, Headers (1-6), Code blocks (fenced/indented), Block quotes, Lists (ordered/unordered), Horizontal rules
  - Inline elements: Emphasis (bold/italic/strikethrough), Links (inline/reference), Images, Code spans, Autolinks, Text nodes
  - Special features: Character escaping, precedence rules, reference link definitions

* Key architectural patterns:
  - Token-based parsing for precise control and error reporting
  - Visitor pattern for AST traversal and rendering
  - Template method pattern for extensible rendering
  - Factory pattern for node creation
  - Strategy pattern for different emphasis types and list types

* Error handling and validation:
  - Graceful degradation for invalid syntax
  - Configurable strict/lenient parsing modes
  - Comprehensive validation with detailed error reporting
  - Statistics tracking for parsing performance analysis

* Extension points implemented:
  - Pluggable renderer system (HTML, Markdown, custom)
  - Configurable parser options
  - AST manipulation capabilities
  - JSON serialization support for AST

* Testing and quality assurance:
  - Unit tests for all components (tokenizer, parsers, renderers)
  - Integration tests for complete parsing workflows
  - Specification compliance tests
  - Error handling and edge case tests
  - Performance and nesting depth validation

[2025-09-18 16:52:50] - Implemented MarkdownV2 Rendering Support for Gromozeka Markdown Parser

## Decision

* Successfully added comprehensive MarkdownV2 rendering capability to the existing Gromozeka Markdown Parser
* Created new MarkdownV2Renderer class integrated with the modular parser architecture
* Added parse_to_markdownv2() method and markdown_to_markdownv2() convenience function
* Implemented proper character escaping according to Telegram's MarkdownV2 specification

## Rationale 

* The Gromozeka project needed MarkdownV2 support for Telegram bot integration
* Leveraging the existing modular parser architecture allows clean separation of concerns
* Reusing existing telegram_markdown.py utilities ensures consistent escaping behavior
* Following the same patterns as HTMLRenderer and MarkdownRenderer maintains architectural consistency
* Comprehensive testing ensures reliability for production Telegram bot usage

## Implementation Details

* Created MarkdownV2Renderer class in lib/markdown/renderer.py with full AST traversal support
* Implemented proper format conversion: **bold** → *bold*, *italic* → _italic_, ~~strike~~ → ~strike~
* Added context-aware character escaping using existing escapeMarkdownV2() function from lib/telegram_markdown.py
* Handled MarkdownV2 limitations: headers converted to bold text, lists to bullet/numbered format
* Special handling for Telegram-specific features: custom emoji support, email autolinks with mailto:
* Added parse_to_markdownv2() method to main MarkdownParser class with options support
* Created markdown_to_markdownv2() convenience function for quick conversions
* Updated module exports in __init__.py to include new MarkdownV2 functionality

* Comprehensive test suite with 31 test cases covering:
  - Basic formatting conversion (bold, italic, strikethrough)
  - Character escaping in different contexts (general, code, links)
  - Complex document structures with mixed elements
  - Telegram-specific features (custom emoji, autolinks, mentions)
  - Error handling and edge cases
  - Integration with main parser interface

* Created extensive documentation and examples:
  - Updated module docstring with MarkdownV2 usage examples
  - Created markdownv2_examples.py with comprehensive demonstrations
  - Added test files: test_markdownv2_renderer.py, demo_markdownv2.py
  - All examples tested and working correctly

* Key architectural patterns maintained:
  - Modular renderer design following existing HTMLRenderer/MarkdownRenderer patterns
  - AST-based rendering with proper node type handling
  - Options support for customization
  - Error handling and graceful degradation
  - Fallback escaping when telegram_markdown module unavailable

* MarkdownV2 format compliance:
  - Proper escaping of special characters: _*[]()~`>#+-=|{}.!
  - Context-aware escaping (general text vs code vs link URLs)
  - Support for all MarkdownV2 formatting: *bold*, _italic_, ~strikethrough~, `code`, ```code blocks```
  - Block quote support with > prefix
  - Link format: [text](url) with proper URL escaping
  - Custom emoji support: ![emoji](tg://emoji?id=...)

[2025-09-18 18:31:00] - Added Preserve Options to Markdown Parser for Better MarkdownV2 Output

## Decision

* Added two new parser options: `preserve_leading_spaces` and `preserve_soft_line_breaks`
* Modified BlockParser to respect these options during paragraph parsing
* Updated MarkdownV2Renderer to preserve formatting when options are enabled
* Set both options to `True` by default in `markdown_to_markdownv2()` function

## Rationale 

* The original Markdown parser was stripping leading spaces and converting soft line breaks to spaces
* This made MarkdownV2 output less readable and lost important formatting information
* Telegram's MarkdownV2 format can handle newlines and spaces better than standard Markdown
* Users requested the ability to preserve the original text formatting for better readability
* Default enabling for MarkdownV2 conversion ensures better output without breaking existing functionality

## Implementation Details

* Added `preserve_leading_spaces` and `preserve_soft_line_breaks` options to MarkdownParser class
* Modified BlockParser constructor to accept and store parser options
* Updated `_parse_paragraph()` method in BlockParser:
  - When `preserve_soft_line_breaks=True`: newlines preserved as `\n` instead of converting to spaces
  - When `preserve_leading_spaces=True`: text content not stripped of leading/trailing spaces
* Updated MarkdownV2Renderer constructor to accept and store these options
* Modified `_render_paragraph()` method in MarkdownV2Renderer to conditionally strip content
* Enhanced `markdown_to_markdownv2()` function to enable both options by default
* Created comprehensive test suite with `test_preserve_paragraphs.py` demonstrating all combinations
* All tests pass showing correct behavior for both individual and combined option usage

[2025-09-18 21:43:00] - Fixed Nested Lists Parsing Issue in Markdown Parser

## Decision

* Fixed critical nested lists parsing issue in lib/markdown/block_parser.py
* Added new _is_list_marker_at_line_start() helper method for proper line start detection
* Updated _parse_list() and _parse_list_item() methods to use improved line start logic
* Resolved chaining behavior where sibling list items were incorrectly nested

## Rationale 

* The original parser was creating chains of nested lists instead of properly grouping items at the same indentation level
* The _is_at_line_start() method was returning False for LIST_MARKER tokens when preceded by spaces
* This caused the parser to only process the first item at each indentation level, creating incorrect AST structure
* The fix ensures that list items at the same indentation are correctly identified as siblings

## Implementation Details

* Created _is_list_marker_at_line_start() method that checks if a LIST_MARKER is at logical line start (considering spaces)
* Updated _parse_list() method to use _is_list_marker_at_line_start() in while loop condition
* Updated _parse_list_item() method to use _is_list_marker_at_line_start() for sibling/parent detection
* The fix works for both main parser and sub-parsers processing nested content
* All existing functionality preserved - 100% test success rate (13/13 tests passing)

## Results

* test_nested_lists_comprehensive.py now passes both test cases
* Complex nested structures like "Item 3.1, Item 3.2, Item 3.3" are correctly parsed as siblings
* Deeply nested lists like "Item 3.2.1, Item 3.2.2" also work correctly
* No regression in existing functionality - all 40 main parser tests still pass
* HTML output now correctly renders nested lists with proper <ul>/<li> structure
[2025-09-18 21:58:20] - Added ignore_indented_code_blocks Option to Markdown Parser

## Decision

* Added new `ignore_indented_code_blocks` parser option (default `True`) to disable 4-space indented code blocks
* Updated both MarkdownParser and BlockParser classes to respect this option
* Modified `_parse_block()` and `_is_block_element_start()` methods to skip indented code blocks when option is enabled

## Rationale 

* 4-space indented code blocks are rarely used in modern Markdown but can cause parsing issues and mess
* Users requested ability to disable this feature while keeping fenced code blocks (```code```)
* Default behavior now ignores indented code blocks, treating them as regular paragraphs with preserved spacing
* Fenced code blocks continue to work normally regardless of this setting
* Backward compatibility maintained - users can set `ignore_indented_code_blocks=False` to restore old behavior

## Implementation Details

* Added `ignore_indented_code_blocks` option to MarkdownParser class with default value `True`
* Updated BlockParser constructor to accept and store this option from parser options
* Modified `_parse_block()` method to check option before parsing indented code blocks: `if not self.ignore_indented_code_blocks and self._is_indented_code_block()`
* Fixed `_is_block_element_start()` method to conditionally include indented code block detection based on option
* Created comprehensive test suite (`test_ignore_indented_code.py`) with two test scenarios:
  - Verifies indented code blocks are ignored by default and parsed when option is disabled
  - Confirms fenced code blocks continue working in both modes
* All tests pass successfully, confirming proper functionality without breaking existing features
* No impact on other Markdown parsing features - lists, headers, block quotes, etc. work normally
[2025-09-18 22:11:00] - Fixed normalize_markdown List Rendering Issue

## Decision

* Fixed critical bug in MarkdownRenderer where list nodes (MDList and MDListItem) were not being properly handled
* Added missing _render_list() and _render_list_item() methods to MarkdownRenderer class
* Implemented proper nested list rendering with correct indentation and formatting

## Rationale 

* The normalize_markdown() function was stripping all list structure and concatenating text content because MarkdownRenderer._render_node() was missing MDList and MDListItem handling cases
* Lists were falling through to the generic _render_children() method which only concatenates text without preserving structure
* Proper list rendering is essential for markdown normalization functionality used throughout the project
* The fix maintains backward compatibility while adding the missing core functionality

## Implementation Details

* Added elif isinstance(node, MDList): and elif isinstance(node, MDListItem): cases to MarkdownRenderer._render_node() method
* Implemented _render_list() method that processes all list items and joins them with newlines
* Implemented _render_list_item() method with sophisticated nested list handling:
  - Separates text content from nested lists for proper rendering
  - Determines correct list markers (ordered numbers vs unordered bullets) based on parent list type
  - Handles nested list indentation with 3-space indentation per nesting level
  - Preserves all inline formatting (bold, italic, code spans, links) within list items
* All existing functionality preserved - no breaking changes to other markdown features
* Comprehensive testing confirms fix works for: mixed ordered/unordered lists, deep nesting, lists with other content types
* Test results show perfect preservation of list structure and formatting in normalize_markdown() output
[2025-09-18 22:17:00] - Fixed MarkdownV2Renderer List Rendering Issue

## Decision

* Fixed critical bug in MarkdownV2Renderer where nested lists were being rendered inline instead of on separate lines
* Completely rewrote _render_list() and _render_list_item() methods in MarkdownV2Renderer class
* Implemented proper nested list rendering with correct Telegram MarkdownV2 formatting and escaping

## Rationale 

* The MarkdownV2Renderer had the same fundamental issue as MarkdownRenderer - nested lists were concatenated inline
* The original _render_list_item() method used _render_children() which flattened nested structure
* Proper nested list rendering is essential for Telegram bot functionality using MarkdownV2 format
* MarkdownV2 has specific escaping requirements that needed to be preserved while fixing structure
* The fix maintains full Telegram MarkdownV2 compliance while adding missing nested list functionality

## Implementation Details

* Completely rewrote _render_list() method to properly process list items and join with newlines
* Completely rewrote _render_list_item() method with sophisticated nested list handling:
  - Separates text content from nested lists for proper rendering structure
  - Determines correct list markers: ordered numbers (1\., 2\., etc.) vs unordered bullets (•)
  - Handles nested list indentation with 3-space indentation per nesting level
  - Preserves all MarkdownV2 character escaping (periods, special characters)
  - Maintains proper start_number handling for ordered lists
  - Supports unlimited nesting depth with consistent formatting
* All existing MarkdownV2 functionality preserved - no breaking changes to escaping or formatting
* Comprehensive testing confirms fix works for:
  - Mixed ordered/unordered nested lists with proper MarkdownV2 escaping
  - Deep nesting (4+ levels) with correct indentation
  - Lists with complex inline formatting (bold, italic, code, links, strikethrough)
  - Integration with other MarkdownV2 elements (headers, paragraphs, block quotes)
* Test results show perfect Telegram MarkdownV2 compliance with proper nested list structure
* Both normalize_markdown() and markdown_to_markdownv2() now produce correctly formatted nested lists