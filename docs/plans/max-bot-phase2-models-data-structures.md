# Task 2.0.0: Max Bot Client Library - Phase 2: Models & Data Structures

**Phase:** Phase 2: Models & Data Structures
**Category:** Library Development
**Priority:** High
**Complexity:** Complex
**Estimated Duration:** 4-5 days
**Assigned To:** Development Team
**Date Created:** 2024-11-16

## Objective

Implement all data models from the Max Messenger API specification as type-safe dataclasses with proper inheritance hierarchy, validation, and serialization support. This includes 60+ model classes covering users, chats, messages, attachments, buttons, updates, and responses.

**Success Definition:** Complete implementation of all API models with proper type hints, inheritance, serialization/deserialization, and comprehensive test coverage.

## Prerequisites

### Dependency Tasks
- [x] **Task 1.0.0:** Phase 1: Core Infrastructure - [Status: Complete]

### Required Artifacts
- [`lib/max_bot/models/base.py`](lib/max_bot/models/base.py) - BaseModel class implementation
- [`lib/max_bot/constants.py`](lib/max_bot/constants.py) - Enums and constants
- [`docs/other/Max-Messenger/swagger.json`](docs/other/Max-Messenger/swagger.json) - API specification

## Detailed Steps

### Step 1: Implement User Models
**Estimated Time:** 3 hours
**Description:** Create user-related model classes with proper inheritance

**Actions:**
- [ ] Create `lib/max_bot/models/user.py`
- [ ] Implement `User` base model with all fields
- [ ] Implement `UserWithPhoto` extending User
- [ ] Implement `BotInfo` extending UserWithPhoto
- [ ] Implement `BotPatch` and `BotCommand` models
- [ ] Add validation for username patterns
- [ ] Preserve all API descriptions as docstrings

**Completion Criteria:**
- All user models match API specification
- Inheritance hierarchy is correct
- Serialization/deserialization works
- Docstrings include API descriptions

**Potential Issues:**
- Nullable field handling
- Mitigation: Use Optional types consistently

### Step 2: Implement Chat Models
**Estimated Time:** 4 hours
**Description:** Create chat-related model classes

**Actions:**
- [ ] Create `lib/max_bot/models/chat.py`
- [ ] Implement `Chat` model with all fields
- [ ] Implement `ChatMember` extending User
- [ ] Implement `ChatAdmin` with permissions
- [ ] Implement `ChatList`, `ChatMembersList`, `ChatAdminsList`
- [ ] Implement `ChatPatch` for updates
- [ ] Add `ChatType` and `ChatStatus` enum usage
- [ ] Handle nullable fields (pinned_message, dialog_with_user)

**Completion Criteria:**
- All chat models are complete
- Enums are properly integrated
- Complex nested structures work
- Pagination support is included

**Potential Issues:**
- Circular dependencies with Message model
- Mitigation: Use forward references and TYPE_CHECKING

### Step 3: Implement Message Core Models
**Estimated Time:** 4 hours
**Description:** Create message-related core model classes

**Actions:**
- [ ] Create `lib/max_bot/models/message.py`
- [ ] Implement `Recipient` model
- [ ] Implement `MessageBody` with attachments field
- [ ] Implement `Message` with sender and recipient
- [ ] Implement `MessageList` for paginated results
- [ ] Implement `MessageStat` for view counts
- [ ] Implement `LinkedMessage` for replies/forwards
- [ ] Add message ID and sequence handling

**Completion Criteria:**
- Message models handle all fields
- Attachments field supports polymorphic types
- Timestamps are properly handled
- Forward/reply messages work

**Potential Issues:**
- Attachment polymorphism complexity
- Mitigation: Use discriminator pattern

### Step 4: Implement Message Request Models
**Estimated Time:** 2 hours
**Description:** Create models for message creation and editing

**Actions:**
- [ ] Implement `NewMessageBody` for sending messages
- [ ] Implement `NewMessageLink` for replies/forwards
- [ ] Implement `SendMessageResult` response model
- [ ] Add `TextFormat` enum usage
- [ ] Add `MessageLinkType` enum usage
- [ ] Implement validation for max message length

**Completion Criteria:**
- Request models match API requirements
- Optional fields are properly handled
- Format field works correctly
- Validation enforces API limits

**Potential Issues:**
- Different requirements for create vs edit
- Mitigation: Clear documentation of differences

### Step 5: Implement Attachment Base Models
**Estimated Time:** 3 hours
**Description:** Create base attachment infrastructure with discriminator

**Actions:**
- [ ] Create `lib/max_bot/models/attachment.py`
- [ ] Implement `Attachment` base class with discriminator
- [ ] Implement attachment type mapping
- [ ] Create payload base classes
- [ ] Implement `AttachmentRequest` base class
- [ ] Set up polymorphic deserialization

**Completion Criteria:**
- Discriminator pattern works correctly
- Type field properly maps to subclasses
- Serialization preserves type information
- Deserialization creates correct subclass

**Potential Issues:**
- Complex discriminator implementation
- Mitigation: Follow OpenAPI discriminator spec

### Step 6: Implement Media Attachments
**Estimated Time:** 4 hours
**Description:** Implement photo, video, audio, and file attachments

**Actions:**
- [ ] Implement `PhotoAttachment` and `PhotoAttachmentPayload`
- [ ] Implement `VideoAttachment` with thumbnail support
- [ ] Implement `AudioAttachment` with transcription
- [ ] Implement `FileAttachment` with size info
- [ ] Implement `StickerAttachment` and payload
- [ ] Add all request models for media
- [ ] Implement `VideoAttachmentDetails` and `VideoUrls`

**Completion Criteria:**
- All media attachments work
- Thumbnails and metadata included
- Token reuse is supported
- URL variants for video handled

**Potential Issues:**
- Large number of similar models
- Mitigation: Use inheritance to reduce duplication

### Step 7: Implement Interactive Attachments
**Estimated Time:** 3 hours
**Description:** Implement contact, location, and share attachments

**Actions:**
- [ ] Implement `ContactAttachment` with VCF support
- [ ] Implement `LocationAttachment` with coordinates
- [ ] Implement `ShareAttachment` for link previews
- [ ] Implement `DataAttachment` for button payloads
- [ ] Add all request models
- [ ] Add coordinate validation for location

**Completion Criteria:**
- All interactive attachments work
- VCF data is properly handled
- Coordinates are validated
- Link preview fields included

**Potential Issues:**
- VCF format complexity
- Mitigation: Store as string, don't parse

### Step 8: Implement Keyboard Models
**Estimated Time:** 4 hours
**Description:** Create keyboard and button model hierarchy

**Actions:**
- [ ] Create `lib/max_bot/models/keyboard.py`
- [ ] Implement `Keyboard` base model
- [ ] Implement `Button` base class with discriminator
- [ ] Implement `InlineKeyboardAttachment` 
- [ ] Implement `ReplyKeyboardAttachment`
- [ ] Add request models for keyboards
- [ ] Document keyboard layout structure

**Completion Criteria:**
- Keyboard structure is correct (2D array)
- All attachment types work
- Request models are complete
- Documentation is clear

**Potential Issues:**
- Complex button hierarchy
- Mitigation: Clear inheritance structure

### Step 9: Implement Button Types
**Estimated Time:** 4 hours
**Description:** Implement all button type variants

**Actions:**
- [ ] Implement `CallbackButton` with payload
- [ ] Implement `LinkButton` with URL
- [ ] Implement `RequestContactButton`
- [ ] Implement `RequestGeoLocationButton`
- [ ] Implement `ChatButton` with chat creation
- [ ] Implement `OpenAppButton` for mini-apps
- [ ] Implement `MessageButton` for quick replies
- [ ] Implement reply button variants
- [ ] Add `Intent` enum usage

**Completion Criteria:**
- All 10+ button types implemented
- Discriminator works correctly
- Payloads are properly typed
- Intent styling supported

**Potential Issues:**
- Many similar but different button types
- Mitigation: Comprehensive testing

### Step 10: Implement Update Models
**Estimated Time:** 5 hours
**Description:** Implement all update event types

**Actions:**
- [ ] Create `lib/max_bot/models/update.py`
- [ ] Implement `Update` base class with discriminator
- [ ] Implement message updates (created, edited, removed)
- [ ] Implement bot updates (added, removed, started, stopped)
- [ ] Implement user updates (added, removed)
- [ ] Implement dialog updates (muted, unmuted, cleared, removed)
- [ ] Implement chat updates (title changed, chat created)
- [ ] Implement `UpdateList` for polling
- [ ] Add `Callback` and `CallbackAnswer` models

**Completion Criteria:**
- All 16+ update types implemented
- Discriminator mapping complete
- Timestamps handled correctly
- User locale field included where applicable

**Potential Issues:**
- Large number of update types
- Mitigation: Systematic testing of each type

### Step 11: Implement Response Models
**Estimated Time:** 2 hours
**Description:** Create API response wrapper models

**Actions:**
- [ ] Create `lib/max_bot/models/response.py`
- [ ] Implement `SimpleQueryResult`
- [ ] Implement `Error` model
- [ ] Implement `Subscription` model
- [ ] Implement `GetSubscriptionsResult`
- [ ] Implement `UploadEndpoint`
- [ ] Implement `ActionRequestBody`
- [ ] Add other utility response models

**Completion Criteria:**
- All response models implemented
- Error codes are documented
- Success/failure handling clear
- Upload response handled

**Potential Issues:**
- Error response variations
- Mitigation: Flexible error parsing

### Step 12: Implement Markup Models
**Estimated Time:** 2 hours
**Description:** Create text markup/formatting models

**Actions:**
- [ ] Create `lib/max_bot/models/markup.py`
- [ ] Implement `MarkupElement` base class
- [ ] Implement all markup types (strong, emphasized, etc.)
- [ ] Implement `LinkMarkup` with URL
- [ ] Implement `UserMentionMarkup`
- [ ] Add position and length handling
- [ ] Create markup builder utilities

**Completion Criteria:**
- All markup types supported
- Position tracking works
- Builder utilities are intuitive
- Documentation includes examples

**Potential Issues:**
- Text position complexity
- Mitigation: Comprehensive position tests

### Step 13: Add Model Validation
**Estimated Time:** 3 hours
**Description:** Add validation methods to all models

**Actions:**
- [ ] Add field validators where needed
- [ ] Validate enum values
- [ ] Check required vs optional fields
- [ ] Validate string patterns (URLs, usernames)
- [ ] Add length limits validation
- [ ] Create custom validation decorators
- [ ] Document validation rules

**Completion Criteria:**
- All API constraints enforced
- Validation errors are informative
- Performance is acceptable
- Validation is documented

**Potential Issues:**
- Performance impact of validation
- Mitigation: Lazy validation option

### Step 14: Create Comprehensive Tests
**Estimated Time:** 4 hours
**Description:** Write unit tests for all model classes

**Actions:**
- [ ] Create test files for each model module
- [ ] Test serialization/deserialization
- [ ] Test inheritance hierarchy
- [ ] Test discriminator patterns
- [ ] Test validation rules
- [ ] Test edge cases and nullables
- [ ] Add fixtures for common data

**Completion Criteria:**
- Test coverage > 90% for models
- All discriminators tested
- Edge cases covered
- Fixtures are reusable

**Potential Issues:**
- Large number of test cases
- Mitigation: Parametrized testing

### Step 15: Documentation and Type Stubs
**Estimated Time:** 2 hours
**Description:** Complete documentation and type hints

**Actions:**
- [ ] Verify all docstrings from API spec
- [ ] Add usage examples to complex models
- [ ] Create type stub files if needed
- [ ] Document model relationships
- [ ] Create model usage guide
- [ ] Add model diagram

**Completion Criteria:**
- All models fully documented
- Examples are practical
- Type checking passes
- Relationships are clear

**Potential Issues:**
- Documentation maintenance burden
- Mitigation: Auto-generate where possible

## Expected Outcome

### Primary Deliverables
- [`lib/max_bot/models/user.py`](lib/max_bot/models/user.py) - User models
- [`lib/max_bot/models/chat.py`](lib/max_bot/models/chat.py) - Chat models
- [`lib/max_bot/models/message.py`](lib/max_bot/models/message.py) - Message models
- [`lib/max_bot/models/attachment.py`](lib/max_bot/models/attachment.py) - Attachment models
- [`lib/max_bot/models/keyboard.py`](lib/max_bot/models/keyboard.py) - Keyboard/button models
- [`lib/max_bot/models/update.py`](lib/max_bot/models/update.py) - Update event models
- [`lib/max_bot/models/response.py`](lib/max_bot/models/response.py) - Response models
- [`lib/max_bot/models/markup.py`](lib/max_bot/models/markup.py) - Text markup models

### Secondary Deliverables
- Test files for all model modules
- Model relationship documentation
- Usage examples and guides

### Quality Standards
- All models match API specification exactly
- Type hints are comprehensive and correct
- Docstrings preserve API descriptions
- Test coverage > 90%
- No circular import issues
- Passes `make format` and `make lint`

### Integration Points
- Models use BaseModel from Phase 1
- Models use enums from constants module
- Ready for use in Phase 3 API operations
- Serialization compatible with httpx

## Testing Criteria

### Unit Testing
- [ ] **Model Creation:** Test all constructors
  - Test with all fields
  - Test with minimal fields
  - Test with invalid data
  
- [ ] **Serialization:** Test to/from dict
  - Test nested structures
  - Test null handling
  - Test type preservation

- [ ] **Validation:** Test all validators
  - Test field constraints
  - Test enum validation
  - Test pattern matching

### Integration Testing
- [ ] **Inheritance:** Test model hierarchy
  - Test method resolution
  - Test field inheritance
  - Test discriminators
  
- [ ] **Polymorphism:** Test type variants
  - Test attachment types
  - Test button types
  - Test update types

### Manual Validation
- [ ] **API Compatibility:** Verify against spec
  - Check field names
  - Check field types
  - Check optionality

### Performance Testing
- [ ] **Serialization Speed:** Measure performance
  - Large message lists
  - Complex attachments
  - Many buttons

## Definition of Done

### Functional Completion
- [ ] All 15 steps completed
- [ ] 60+ models implemented
- [ ] All discriminators working
- [ ] Validation is comprehensive

### Quality Assurance
- [ ] All tests passing
- [ ] Coverage > 90%
- [ ] Type checking passes
- [ ] No linting errors

### Documentation
- [ ] All models documented
- [ ] API descriptions preserved
- [ ] Examples provided
- [ ] Relationships documented

### Integration and Deployment
- [ ] Models importable
- [ ] No circular imports
- [ ] Ready for Phase 3

### Administrative
- [ ] Report created
- [ ] Time tracked
- [ ] Phase 3 prepared
- [ ] Code committed

---

**Related Tasks:**
**Previous:** Phase 1: Core Infrastructure
**Next:** Phase 3: Basic Operations
**Parent Phase:** Max Bot Client Library Implementation

---

## Notes

This phase involves implementing a large number of interrelated models. Key considerations:
- Maintain consistent patterns across all models
- Careful attention to the discriminator pattern for polymorphic types
- Preserve all API documentation in docstrings
- Consider using code generation for repetitive models
- Group related models to avoid circular imports