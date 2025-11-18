# Task: Max Bot Attachment Types Implementation

**Phase:** Max Bot Client Development
**Category:** Models & Data Structures
**Priority:** High
**Complexity:** Complex
**Estimated Duration:** 5-7 days
**Assigned To:** Development Team
**Date Created:** 2025-11-18

## Objective

Implement all remaining attachment types for the Max Bot client to achieve complete feature parity with the Max Messenger API specification. Currently only PhotoAttachment (1/11 types) is implemented, leaving 10 attachment types missing. This implementation will enable the bot to handle all media types, interactive elements, and special attachments as defined in the API.

**Success Definition:** All 11 attachment types are fully implemented with proper inheritance hierarchy, factory function support, and comprehensive test coverage.

## Prerequisites

### Dependency Tasks
- [x] **Max Bot Phase 2:** Models and Data Structures - [Status: Complete]
- [x] **PhotoAttachment Implementation:** Reference implementation - [Status: Complete]
- [x] **Base Attachment Class:** Core infrastructure - [Status: Complete]

### Required Artifacts
- [`lib/max_bot/models/attachment.py`](lib/max_bot/models/attachment.py) - Existing attachment module with PhotoAttachment
- [`lib/max_bot/models/common.py`](lib/max_bot/models/common.py) - Common models and enums
- [`lib/max_bot/models/base.py`](lib/max_bot/models/base.py) - Base model infrastructure
- [`docs/other/Max-Messenger/swagger-2025.11.16.json`](docs/other/Max-Messenger/swagger-2025.11.16.json) - API specification reference

## Detailed Steps

### Phase 1: Base Payload Classes
**Estimated Time:** 4 hours
**Description:** Implement the foundational payload classes that will be inherited by specific attachment types

**Actions:**
- [ ] Create AttachmentPayload base class with common fields
- [ ] Create MediaAttachmentPayload extending AttachmentPayload
- [ ] Create FileAttachmentPayload extending AttachmentPayload
- [ ] Add proper field validation and nullable handling
- [ ] Write docstrings for all new classes

**Completion Criteria:**
- Base payload classes match API specification exactly
- Inheritance hierarchy is properly established
- All nullable fields are handled correctly
- Type hints are comprehensive

**Potential Issues:**
- Complex nullable field handling in pydantic
- Mitigation: Use Optional types and Field defaults consistently

### Phase 2: Simple Attachments Implementation
**Estimated Time:** 6 hours
**Description:** Implement the three simplest attachment types that have minimal dependencies

**Actions:**
- [ ] Implement LocationAttachment (special case - no payload, lat/lon fields)
- [ ] Implement AudioAttachment with MediaAttachmentPayload
- [ ] Implement FileAttachment with FileAttachmentPayload
- [ ] Add AttachmentType enum values for each
- [ ] Update discriminator mapping in base Attachment class

**Completion Criteria:**
- All three simple attachments work with proper serialization
- LocationAttachment handles direct lat/lon fields correctly
- Audio and File attachments use appropriate payload classes
- Factory functions can create these attachments

**Potential Issues:**
- LocationAttachment's unique structure (no payload field)
- Mitigation: Use custom field mapping or special handling in the class

### Phase 3: Medium Complexity Attachments
**Estimated Time:** 8 hours
**Description:** Implement attachments that require custom payload classes and references to other models

**Actions:**
- [ ] Create StickerAttachmentPayload class
- [ ] Implement StickerAttachment with StickerAttachmentPayload
- [ ] Create ShareAttachmentPayload with url and title fields
- [ ] Implement ShareAttachment
- [ ] Create ContactAttachmentPayload with User reference
- [ ] Implement ContactAttachment
- [ ] Import User model if not already available
- [ ] Update discriminator mappings

**Completion Criteria:**
- All three medium complexity attachments are fully functional
- User model is properly integrated in ContactAttachment
- Share attachment handles URLs and titles correctly
- Sticker attachment supports all required fields

**Potential Issues:**
- Circular import with User model
- Mitigation: Use forward references or TYPE_CHECKING imports

### Phase 4: Video Attachment Complex Implementation
**Estimated Time:** 8 hours
**Description:** Implement the most complex attachment type with multiple supporting classes

**Actions:**
- [ ] Create VideoThumbnail model with url, width, height fields
- [ ] Create VideoUrls model for different quality URLs
- [ ] Create VideoAttachmentDetails model
- [ ] Create VideoAttachmentPayload extending MediaAttachmentPayload
- [ ] Implement VideoAttachment class
- [ ] Handle nullable fields in video components
- [ ] Add comprehensive validation for video dimensions

**Completion Criteria:**
- Video attachment supports all quality levels
- Thumbnail handling works correctly
- All nested models serialize/deserialize properly
- Complex nullable field combinations work

**Potential Issues:**
- Complex nested model structure
- Mitigation: Test each component independently before integration

### Phase 5: Interactive Keyboard Attachments
**Estimated Time:** 10 hours
**Description:** Implement keyboard-based interactive attachments

**Actions:**
- [ ] Import or create Keyboard model from keyboard.py
- [ ] Import or create Button model
- [ ] Implement InlineKeyboardAttachment with Keyboard payload
- [ ] Implement ReplyKeyboardAttachment (check discriminator mapping)
- [ ] Handle keyboard layout and button actions
- [ ] Ensure proper integration with interactive.py models

**Completion Criteria:**
- Both keyboard types work with proper button layouts
- Callback actions are properly handled
- Keyboard models integrate seamlessly
- Discriminator issues are resolved

**Potential Issues:**
- ReplyKeyboardAttachment not in discriminator mapping
- Mitigation: Investigate API spec for correct type value

### Phase 6: Special Case - DataAttachment
**Estimated Time:** 4 hours
**Description:** Implement the DataAttachment type which is not in the current discriminator

**Actions:**
- [ ] Investigate DataAttachment structure from API spec
- [ ] Create DataAttachmentPayload if needed
- [ ] Implement DataAttachment class
- [ ] Determine correct discriminator value
- [ ] Add to factory function support

**Completion Criteria:**
- DataAttachment purpose and structure understood
- Implementation matches API requirements
- Discriminator value correctly identified

**Potential Issues:**
- Unknown structure and purpose
- Mitigation: Deep dive into API spec or contact API maintainers

### Phase 7: Factory Function Updates
**Estimated Time:** 4 hours
**Description:** Update the attachment factory function to support all new types

**Actions:**
- [ ] Update createAttachmentFromDict function
- [ ] Add support for all 10 new attachment types
- [ ] Handle special cases (Location, keyboards, Data)
- [ ] Add proper error handling for unknown types
- [ ] Write comprehensive factory tests

**Completion Criteria:**
- Factory function creates all 11 attachment types correctly
- Unknown types are handled gracefully
- Type discrimination works reliably

**Potential Issues:**
- Complex type discrimination logic
- Mitigation: Use clear switch/case pattern with explicit type checking

### Phase 8: Comprehensive Testing
**Estimated Time:** 8 hours
**Description:** Create comprehensive test suite for all attachment types

**Actions:**
- [ ] Create test fixtures for each attachment type
- [ ] Write serialization tests for all attachments
- [ ] Write deserialization tests for all attachments
- [ ] Test nullable field combinations
- [ ] Test factory function with various inputs
- [ ] Test edge cases and error conditions
- [ ] Integration tests with actual API responses

**Completion Criteria:**
- 100% code coverage for new attachment types
- All tests pass consistently
- Edge cases are properly handled
- Real API response fixtures work correctly

**Potential Issues:**
- Complex test data preparation
- Mitigation: Use fixture files from API documentation

## Expected Outcome

### Primary Deliverables
- [`lib/max_bot/models/attachment.py`](lib/max_bot/models/attachment.py) - Updated with all 11 attachment types
- [`tests/lib_max_bot/test_attachments.py`](tests/lib_max_bot/test_attachments.py) - Comprehensive test suite
- Properly functioning attachment system for Max Bot client

### Secondary Deliverables
- Updated documentation for each attachment type
- Example usage for each attachment in docstrings
- Migration guide if API changes detected

### Quality Standards
- All attachment types match API specification exactly
- Comprehensive type hints and docstrings
- No mypy/pylint errors
- Test coverage > 95%
- Consistent code style matching existing codebase

### Integration Points
- Message model uses attachments correctly
- Client can send/receive all attachment types
- Handlers can process all attachment types
- Serialization/deserialization works bidirectionally

## Testing Criteria

### Unit Testing
- [ ] **Payload Classes:** Test all base payload classes
  - Field validation
  - Nullable field handling
  - Inheritance chain

- [ ] **Simple Attachments:** Test Location, Audio, File
  - Serialization to dict
  - Deserialization from dict
  - Edge cases with missing fields

- [ ] **Complex Attachments:** Test Video, Contact, Share, Sticker
  - Nested model handling
  - Reference resolution (User model)
  - All field combinations

- [ ] **Interactive Attachments:** Test keyboard attachments
  - Button layouts
  - Callback handling
  - Keyboard types differentiation

### Integration Testing
- [ ] **Factory Function:** Test createAttachmentFromDict
  - All type discrimination paths
  - Error handling for unknown types
  - Performance with large payloads

- [ ] **API Compatibility:** Test with real API responses
  - Parse actual Max Messenger responses
  - Send attachments to API
  - Round-trip serialization

### Manual Validation
- [ ] **Visual Inspection:** Review generated JSON
  - Matches API specification format
  - No extra or missing fields
  - Proper null handling

- [ ] **Bot Testing:** Test with actual bot
  - Send each attachment type
  - Receive each attachment type
  - Handle user interactions

### Performance Testing
- [ ] **Serialization Speed:** Benchmark performance
  - Target: < 1ms per attachment
  - Memory usage reasonable
  - No memory leaks

## Definition of Done

### Functional Completion
- [ ] All 10 remaining attachment types implemented
- [ ] Factory function supports all types
- [ ] All attachments serialize/deserialize correctly
- [ ] Discriminator mapping is complete and accurate

### Quality Assurance
- [ ] All unit tests passing
- [ ] All integration tests passing
- [ ] Code review completed
- [ ] No linting errors (mypy, pylint, ruff)
- [ ] Performance benchmarks met

### Documentation
- [ ] All classes have comprehensive docstrings
- [ ] Usage examples provided
- [ ] API compatibility documented
- [ ] README updated with attachment examples

### Integration and Deployment
- [ ] Changes integrated with main branch
- [ ] No breaking changes to existing code
- [ ] Bot can use all attachment types
- [ ] Backwards compatibility maintained

### Administrative
- [ ] Implementation report created
- [ ] Test coverage report generated
- [ ] Performance metrics documented
- [ ] Known issues or limitations documented

## Technical Considerations

### Inheritance Hierarchy
```
Attachment (base)
├── PhotoAttachment (existing)
├── VideoAttachment
│   └── VideoAttachmentPayload
│       └── MediaAttachmentPayload
│           └── AttachmentPayload
├── AudioAttachment
│   └── MediaAttachmentPayload
├── FileAttachment
│   └── FileAttachmentPayload
├── LocationAttachment (special - no payload)
├── StickerAttachment
│   └── StickerAttachmentPayload
├── ContactAttachment
│   └── ContactAttachmentPayload
├── ShareAttachment
│   └── ShareAttachmentPayload
├── InlineKeyboardAttachment
├── ReplyKeyboardAttachment
└── DataAttachment
```

### Nullable Field Handling
- Use Optional[Type] for all nullable fields
- Provide default None values in Field definitions
- Handle None checks in validation methods
- Document nullable behavior in docstrings

### Special Cases
1. **LocationAttachment**: No payload field, lat/lon at root level
2. **ReplyKeyboardAttachment**: Not in discriminator, investigate type value
3. **DataAttachment**: Unknown structure, requires investigation
4. **Keyboard Attachments**: Complex interaction with Button models

### Factory Function Strategy
```python
def createAttachmentFromDict(data: Dict[str, Any]) -> Optional[Attachment]:
    attachment_type = data.get("type")
    
    type_mapping = {
        AttachmentType.PHOTO: PhotoAttachment,
        AttachmentType.VIDEO: VideoAttachment,
        AttachmentType.AUDIO: AudioAttachment,
        AttachmentType.FILE: FileAttachment,
        AttachmentType.LOCATION: LocationAttachment,
        AttachmentType.STICKER: StickerAttachment,
        AttachmentType.CONTACT: ContactAttachment,
        AttachmentType.SHARE: ShareAttachment,
        AttachmentType.INLINE_KEYBOARD: InlineKeyboardAttachment,
        AttachmentType.REPLY_KEYBOARD: ReplyKeyboardAttachment,
        AttachmentType.DATA: DataAttachment,
    }
    
    attachment_class = type_mapping.get(attachment_type)
    if attachment_class:
        return attachment_class(**data)
    
    return None  # or raise UnknownAttachmentType
```

---

**Related Tasks:**
**Previous:** Max Bot Phase 2 - Models and Data Structures
**Next:** Max Bot Advanced Features Integration
**Parent Phase:** Max Bot Client Development

---

## Implementation Notes

1. **Priority Order**: Follow the phases sequentially as each builds on the previous
2. **API Specification**: Always refer to swagger-2025.11.16.json for exact field names and types
3. **Backwards Compatibility**: Ensure existing PhotoAttachment continues to work
4. **Error Handling**: Implement graceful degradation for unknown attachment types
5. **Testing First**: Consider TDD approach for complex attachments like Video
6. **Code Reuse**: Leverage existing patterns from PhotoAttachment implementation