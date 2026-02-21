# ♿ MERID Accessibility WCAG 2.2 AA Checklist

**Purpose:** Ensure MERID's unified UI meets WCAG 2.2 Level AA accessibility standards for US compliance  
**Version:** 1.0  
**Date:** 2026-01-26  
**Standard:** WCAG 2.2 Level AA  
**Compliance:** ADA-aligned for US web applications  

---

## 📋 **PERCEIVABLE (Information must be presentable in ways users can perceive)**

### **1.1 Non-text Content**

- [ ] **Alt text for meaningful images**
  - All informative images have descriptive alt text
  - Decorative images have empty alt attributes (alt="")
  - Complex images have detailed descriptions nearby
  - Charts and graphs have data table alternatives

- [ ] **Alt text for functional images**
  - Icons used as buttons have descriptive alt text
  - Link images have alt text describing link destination
  - Image maps have alt text for each clickable area
  - CAPTCHA alternatives provide audio or text options

- [ ] **Labels and instructions**
  - Form fields have visible labels programmatically associated
  - Instructions are clear and programmatically detectable
  - Error messages identify required fields clearly
  - Placeholders are not used as the only label

### **1.2 Time-based Media**

- [ ] **Audio and video content**
  - Pre-recorded video has captions
  - Pre-recorded audio has transcripts
  - Live video has real-time captions when available
  - Media controls are keyboard accessible

- [ ] **Sign language interpretation**
  - Pre-recorded video with important audio has sign language
  - Sign language interpretation is synchronized with audio
  - Multiple sign language options considered for diverse users

- [ ] **Audio descriptions**
  - Pre-recorded video has audio descriptions for visual content
  - Audio descriptions are synchronized with video
  - Alternative text descriptions provided for complex visual information

### **1.3 Adaptable**

- [ ] **Info and relationships**
  - Semantic HTML elements used appropriately (header, nav, main, etc.)
  - Table headers properly marked with <th> and scope attributes
  - Form labels properly associated with inputs
  - Lists marked up as proper list elements

- [ ] **Meaningful sequence**
  - Content reading order is logical and programmatically correct
  - Table reading order is meaningful
  - Form field order follows logical progression
  - CSS reordering doesn't affect screen reader order

- [ ] **Sensory characteristics**
  - Instructions don't rely solely on color, shape, or position
  - Audio cues have visual alternatives
  - Visual indicators have text alternatives
  - Warnings provided for flashing content

### **1.4 Distinguishable**

- [ ] **Use of color**
  - Information not conveyed by color alone
  - Color combinations have sufficient contrast
  - Focus indicators are clearly visible
  - Links are identifiable without color

- [ ] **Audio control**
  - Audio that plays automatically has controls
  - Audio can be paused or stopped independently
  - Audio volume can be controlled independently
  - Background audio is low enough not to obscure speech

- [ ] **Contrast**
  - Text contrast ratio ≥ 4.5:1 for normal text
  - Large text (18pt+ or 14pt+ bold) contrast ≥ 3:1
  - Graphical objects and essential icons have sufficient contrast
  - Custom controls meet contrast requirements

- [ ] **Text resizing**
  - Text can be resized up to 200% without loss of content or functionality
  - Reflow works when text is resized
  - No horizontal scrolling required at 400% zoom
  - Images and containers resize appropriately

- [ ] **Images of text**
  - Images of text are avoided unless essential
  - When used, images of text can be resized
  - Text styling is implemented with CSS instead of images
  - Custom fonts maintain readability when resized

- [ ] **Low vision enhancements**
  - High contrast mode is supported
  - Text spacing can be adjusted
  - Color and contrast can be customized
  - Text decoration doesn't affect readability

- [ ] **Reflow**
  - Content reflows into single column at 400% zoom
  - No loss of content or functionality when reflowed
  - Scrolling required in only one direction
  - Tables and forms remain functional when reflowed

---

## 📋 **OPERABLE (Interface components must be operable)**

### **2.1 Keyboard Accessible**

- [ ] **Keyboard functionality**
  - All functionality available via keyboard
  - No keyboard traps (focus can always move away)
  - Focus order is logical and intuitive
  - Keyboard focus is clearly visible

- [ ] **No keyboard trap**
  - Focus can move to and from all components
  - Modal dialogs can be closed with keyboard
  - Focus returns to correct location after modal closure
  - Custom components don't trap focus

- [ ] **Focus order**
  - Focus follows logical reading order
  - Skip links provided for main content
  - Focus indicators are clearly visible
  - Focus moves predictably through interactive elements

### **2.2 Enough Time**

- [ ] **Timing adjustable**
  - Time limits can be extended or disabled
  - Users are warned before time expires
  - Time limits are essential to the task
  - 20+ seconds provided for reading and response

- [ ] **Pause, stop, hide**
  - Moving, blinking, or scrolling content can be paused
  - Auto-updating content can be controlled
  - Blinking content stops after 5 seconds or can be paused
  - Animation frequency is below seizure threshold

### **2.3 Seizures and Physical Reactions**

- [ ] **No flashing content**
  - Content doesn't flash more than 3 times per second
  - Flashing content is below seizure thresholds
  - Red flash thresholds are not exceeded
  - Users are warned before flashing content

- [ ] **Animation control**
  - Parallax effects can be disabled
  - Motion animations can be reduced
  - Auto-playing animations have controls
  - Respect prefers-reduced-motion setting

### **2.4 Navigable**

- [ ] **Bypass blocks**
  - Skip links provided to main content
  - Multiple navigation regions can be bypassed
  - Heading structure is logical and consistent
  - Landmarks identify page regions

- [ ] **Page titles**
  - Page titles are descriptive and unique
  - Page titles identify page content and purpose
  - Page titles change when content changes
  - Frame titles are descriptive when used

- [ ] **Focus order**
  - Focus order preserves meaning and operation
  - Sequential navigation follows logical order
  - Focus moves through components in predictable way
  - Focus order is consistent across similar pages

- [ ] **Link purpose**
  - Link text is descriptive when taken out of context
  - Link purpose can be determined from text alone
  - Multiple links with same text have different purposes
  - Link context is provided programmatically

- [ ] **Heading levels**
  - Heading levels are nested correctly
  - Heading levels are not skipped
  - Headings describe the content that follows
  - Heading structure is consistent across pages

- [ ] **Orientation**
  - Content doesn't restrict to portrait or landscape
  - Display orientation doesn't limit functionality
  - Content works in both orientations
  - Device orientation is not locked

### **2.5 Input Modalities**

- [ ] **Pointer gestures**
  - Complex gestures are not required
  - Path-based gestures have simple alternatives
  - Dragging actions have alternative methods
  - Multi-point gestures are not required

- [ ] **Pointer cancellation**
  - Operations can be undone or aborted
  - Down events don't trigger actions
  - Up events can trigger actions
  - Actions can be cancelled before completion

- [ ] **Label in name**
  - Accessible name contains visible label text
  - Labels are programmatically associated
  - Icon buttons have text labels
  - Custom controls have proper labels

- [ ] **Motion actuation**
  - Functionality doesn't require device motion
  - Motion-based operations have alternatives
  - Device motion is not required for operation
  - Motion sensors are not essential

---

## 📋 **UNDERSTANDABLE (Information and UI operation must be understandable)**

### **3.1 Readable**

- [ ] **Language of page**
  - Default human language is programmatically determined
  - Language changes are indicated
  - Language codes are correct (en, es, etc.)
  - Multiple languages are properly marked

- [ ] **Language of parts**
  - Passages in different languages are identified
  - Foreign language content has proper lang attributes
  - Proper names and technical terms handled correctly
  - Language changes are programmatically detectable

- [ ] **Reading level**
  - Text content requires reading level no more than lower secondary education
  - Complex terms are explained or defined
  - Supplementary content provides explanations
  - Technical terms have glossary definitions

- [ ] **Unusual words**
  - Abbreviations are explained on first use
  - Technical terms are defined or explained
  - Idioms and jargon are avoided or explained
  - Complex sentence structures are simplified

- [ ] **Abbreviations**
  - Abbreviations are expanded on first use
  - Acronyms are defined or explained
  - Abbreviation expansions are available
  - Technical abbreviations are clarified

- [ ] **Pronunciation**
  - Pronunciation is provided for unusual words
  - Phonetic guides are available when needed
  - Foreign words have pronunciation aids
  - Technical terms have pronunciation guides

### **3.2 Predictable**

- [ ] **On focus**
  - Components don't change context on focus
  - Form submission doesn't occur on focus
  - New windows don't open on focus
  - Focus changes don't cause unexpected behavior

- [ ] **On input**
  - Changing settings doesn't cause substantial changes
  - Form submission is user-initiated
  - Data entry doesn't trigger navigation
  - Component behavior is predictable

- [ ] **Consistent navigation**
  - Navigation is consistent across pages
  - Repeated components appear in same order
  - Identical functionality has consistent labeling
  - Navigation patterns are predictable

- [ ] **Consistent identification**
  - Components with same function have same identification
  - Icons are used consistently
  - Button styles are consistent
  - Interactive elements are consistently styled

- [ ] **Change notification**
  - Content changes are notified to users
  - Status updates are clearly communicated
  - Error states are immediately apparent
  - Form validation feedback is timely

### **3.3 Input Assistance**

- [ ] **Error identification**
  - Errors are identified and described to users
  - Error messages are specific and helpful
  - Errors are programmatically associated with fields
  - Error indicators are visually and programmatically clear

- [ ] **Labels or instructions**
  - Labels and instructions are provided
  - Required fields are clearly marked
  - Input format is specified when needed
  - Help text is available when needed

- [ ] **Error suggestion**
  - Suggestions for fixing errors are provided
  - Input format examples are given
  - Common error solutions are suggested
  - Recovery paths are clear

- [ ] **Error prevention (legal, financial, data)**
  - Important actions have confirmation steps
  - Data deletion is reversible or confirmed
  - Financial transactions require confirmation
  - Legal commitments require explicit confirmation

- [ ] **Error prevention (user input)**
  - Input validation occurs before submission
  - Format requirements are clearly communicated
  - Character limits are enforced and indicated
  - Required fields are validated

- [ ] **Help**
  - Help content is available and accessible
  - Context-sensitive help is provided
  - Contact information is easily accessible
  - Support options are clearly available

---

## 📋 **ROBUST (Content must be robust enough for various assistive technologies)**

### **4.1 Compatible**

- [ ] **Parsing**
  - HTML elements have complete start and end tags
  - Elements are nested according to specifications
  - Elements have unique IDs
  - HTML validates against chosen schema

- [ ] **Name, role, value**
  - Custom components have appropriate ARIA roles
  - States and properties are set correctly
  - Value changes are programmatically announced
  - Custom controls follow accessibility patterns

- [ ] **Status messages**
  - Status messages are programmatically determined
  - Important messages are announced to screen readers
  - Error messages are immediately accessible
  - Success confirmations are communicated

- [ ] **Contrast**
  - Custom controls meet contrast requirements
  - Focus indicators meet contrast requirements
  - Error states meet contrast requirements
  - Disabled states meet contrast requirements

---

## 🎯 **MERID-SPECIFIC ACCESSIBILITY REQUIREMENTS**

### **Trading Interface Accessibility**

- [ ] **Real-time data accessibility**
  - Price updates are announced to screen readers
  - Order status changes are programmatically communicated
  - P&L changes are accessible without vision
  - Alert notifications are accessible

- [ ] **Chart accessibility**
  - Charts have data table alternatives
  - Chart trends are described in text
  - Interactive charts have keyboard navigation
  - Chart colors have sufficient contrast

- [ ] **Form accessibility**
  - Order forms have proper labels and descriptions
  - Input validation errors are clearly communicated
  - Required fields are programmatically identified
  - Form submission status is accessible

- [ ] **Table accessibility**
  - Order and position tables have proper headers
  - Table sorting is keyboard accessible
  - Table content is programmatically readable
  - Complex tables have captions and summaries

### **Risk Management Accessibility**

- [ ] **Alert system accessibility**
  - Risk alerts are accessible to screen readers
  - Alert severity is communicated non-visually
  - Alert actions are keyboard accessible
  - Alert history is accessible

- [ ] **Kill switch accessibility**
  - Emergency controls are keyboard accessible
  - Kill switch status is programmatically announced
  - Confirmation dialogs are accessible
  - Emergency procedures are documented accessibly

- [ ] **Limit configuration accessibility**
  - Limit adjustment controls are accessible
  - Current limit values are programmatically available
  - Limit breach warnings are accessible
  - Risk indicators are not color-only

### **Dashboard Accessibility**

- [ ] **Widget accessibility**
  - Dashboard widgets have proper headings
  - Widget content is programmatically readable
  - Widget navigation is keyboard accessible
  - Widget updates are communicated

- [ ] **Navigation accessibility**
  - Main navigation is keyboard accessible
  - Current page is programmatically identified
  - Navigation landmarks are properly marked
  - Skip links are provided

- [ ] **Data visualization accessibility**
  - Graphs and charts have text alternatives
  - Data trends are described in text
  - Color coding is supplemented with text
  - Interactive elements are keyboard accessible

---

## 🔧 **TECHNICAL IMPLEMENTATION CHECKLIST**

### **HTML Structure**

- [ ] **Semantic HTML**
  - Proper use of header, nav, main, section, article, aside, footer
  - Headings used hierarchically (h1, h2, h3, etc.)
  - Lists marked up as ul, ol, or dl
  - Tables used only for tabular data

- [ ] **Form structure**
  - Labels associated with inputs using for/id attributes
  - Fieldset and legend for related form controls
  - Input types used appropriately (email, tel, number, etc.)
  - Required attributes for required fields

- [ ] **Link structure**
  - Descriptive link text
  - Title attributes for additional context when needed
  - Skip links for keyboard navigation
  - Link relationships indicated (rel, aria-describedby)

### **ARIA Implementation**

- [ ] **Landmarks**
  - aria-label or aria-labelledby for landmark regions
  - role attributes for custom components
  - aria-live regions for dynamic content
  - aria-describedby for additional context

- [ ] **States and properties**
  - aria-expanded for expandable content
  - aria-selected for selected items
  - aria-disabled for disabled controls
  - aria-invalid for validation errors

- [ ] **Roles**
  - Proper roles for custom components
  - role="application" for complex interactive areas
  - role="dialog" for modal windows
  - role="alert" for important messages

### **Keyboard Navigation**

- [ ] **Tab order**
  - Logical tab order through interactive elements
  - tabindex="0" for elements that should be focusable
  - tabindex="-1" for elements that need programmatic focus
  - No tabindex > 0 (avoids tab order issues)

- [ ] **Keyboard events**
  - Enter and Space key support for interactive elements
  - Arrow key navigation for menus and lists
  - Escape key for closing modals and menus
  - Keyboard shortcuts documented and accessible

### **Focus Management**

- [ ] **Focus indicators**
  - Visible focus indicators for all interactive elements
  - High contrast focus indicators
  - Focus indicators that work with custom styling
  - Focus indicators that don't rely on color alone

- [ ] **Focus trapping**
  - Focus trapped within modal dialogs
  - Focus returned to original element after modal closure
  - Focus management for custom components
  - No focus traps in non-modal contexts

---

## 📊 **TESTING PROCEDURES**

### **Automated Testing**

- [ ] **Accessibility testing tools**
  - axe-core integration for automated testing
  - WAVE toolbar for manual testing
  - Screen reader testing with NVDA and VoiceOver
  - Keyboard-only navigation testing

- [ ] **Color contrast testing**
  - Contrast ratio verification for all text
  - Contrast testing for interactive elements
  - Testing in high contrast mode
  - Testing with color blindness simulators

### **Manual Testing**

- [ ] **Screen reader testing**
  - NVDA (Windows) testing
  - VoiceOver (Mac) testing
  - JAWS (Windows) testing when available
  - Mobile screen reader testing

- [ ] **Keyboard testing**
  - Tab navigation through all elements
  - Enter/Space key functionality
  - Arrow key navigation
  - Escape key functionality

- [ ] **Visual testing**
  - High contrast mode testing
  - Text-only browser testing
  - Zoom testing (200%, 400%)
  - Mobile accessibility testing

### **User Testing**

- [ ] **Users with disabilities**
  - Testing with screen reader users
  - Testing with keyboard-only users
  - Testing with users with low vision
  - Testing with users with motor disabilities

- [ ] **Task-based testing**
  - Complete trading workflows
  - Risk management procedures
  - Dashboard navigation
  - Emergency procedures

---

## 📈 **COMPLIANCE DOCUMENTATION**

### **Accessibility Statement**

- [ ] **Public accessibility statement**
  - Commitment to accessibility
  - Conformance level (WCAG 2.2 AA)
  - Known limitations and exceptions
  - Contact information for accessibility issues

- [ ] **Technical documentation**
  - Accessibility features documentation
  - Keyboard shortcuts documentation
  - Screen reader usage guide
  - Alternative access methods

### **Training and Support**

- [ ] **Developer training**
  - Accessibility best practices training
  - ARIA usage training
  - Testing procedures training
  - Ongoing accessibility education

- [ ] **Support staff training**
  - Accessibility issue handling
  - Assistive technology basics
  - Communication with users with disabilities
  - Alternative support methods

---

## ✅ **SUCCESS CRITERIA**

### **Launch Requirements**

- [ ] **100% WCAG 2.2 AA compliance for critical user paths**
- [ ] **Screen reader compatibility with NVDA and VoiceOver**
- [ ] **Full keyboard navigation for all features**
- [ ] **Color contrast compliance for all text and interactive elements**
- [ ] **Accessibility statement published and maintained**

### **Ongoing Requirements**

- [ ] **Regular accessibility audits (quarterly)**
- [ ] **New feature accessibility reviews**
- [ ] **User testing with people with disabilities**
- [ ] **Accessibility issue tracking and resolution**
- [ ] **Continuous improvement based on user feedback**

---

## 📝 **TESTING CHECKLIST**

**Test Date:** _________________________  
**Tester:** _____________________________  
**Environment:** _________________________  
**Tools Used:** ___________________________

**WCAG 2.2 AA Compliance:**
- [ ] **Perceivable:** All criteria met
- [ ] **Operable:** All criteria met
- [ ] **Understandable:** All criteria met
- [ ] **Robust:** All criteria met

**MERID-Specific Requirements:**
- [ ] **Trading interface fully accessible**
- [ ] **Risk management features accessible**
- [ ] **Dashboard navigation accessible**
- [ ] **Emergency procedures accessible**

**Testing Results:**
- **Automated tests passed:** [ ] / [ ]
- **Manual tests passed:** [ ] / [ ]
- **User testing completed:** [ ] Yes / [ ] No
- **Critical issues found:** [ ]

**Go/No-Go Decision:**
- [ ] **GO** - Fully compliant, ready for launch
- [ ] **NO-GO** - Critical issues must be resolved
- [ ] **CONDITIONAL** - Minor issues, proceed with plan

**Issues Identified:**
1. _________________________________________________________
2. _________________________________________________________
3. _________________________________________________________

**Resolution Plan:**
1. _________________________________________________________
2. _________________________________________________________
3. _________________________________________________________

---

**Last Updated:** 2026-01-26  
**Next Review:** Quarterly or after major UI changes  
**Owner:** MERID Accessibility Team  
**Compliance Standard:** WCAG 2.2 Level AA (US ADA-aligned)
