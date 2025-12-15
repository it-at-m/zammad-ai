# ADR 04: Knowledge Management System Selection

| Status   | proposed       |
| -------- | -------------- |
| Author   | LB, PI         |
| Voters   | LB, PI, FR, GO |
| Drafted  | 2025-11-19     |
| Accepted | 2025-12-05     |

## Context and Problem Statement

To generate precise and helpful draft responses for tickets in Zammad, the LLM requires comprehensive context. Particularly for the driver's license authority, this includes structured knowledge articles on specific topics (e.g., laws or regulations regarding driver's licenses) as well as clear rules for assigning inquiries to the respective categories. A central knowledge management system that is continuously maintained by the department and serves as a reliable knowledge source for the LLM is required.

### The following criteria are relevant for the decision:

- **Department Access:** The department must be able to independently create, edit, and delete knowledge articles.
- **API:** An API must be available through which knowledge articles can be automatically retrieved (scraped).
- **Document Management and Links:** The system should enable document storage as well as linking to external websites.
- **Rights and Role Concept:** A differentiated rights concept must ensure that access and modifications can be controlled accordingly.
- **Backup / Export Capability:** The system must support complete exports of all knowledge articles including metadata and attachments, thus enabling backups to ensure migrations and restorations.

### Additional desirable criteria:

- **Update Notifications:** The API should be able to provide information about document updates.
- **Self-Hosting:** It should be possible to operate the system independently (e.g., in the cloud, on-premise).
- **Article Labeling:** Knowledge articles should be able to be tagged with labels (e.g., for assignment to subcategories).

## Considered Options

- Magnolia
- Liferay
- BlueSpice Wiki
- Zammad Knowledgebase

## Evaluation

### Magnolia

**Description:** Enterprise Content Management System with Headless CMS functionality already in use at LHM but hosted by SWM.

**Functionalities:**

- Content Management and Digital Asset Management
- REST APIs
- Tagging and categorization
- Workflow management
- PDF document management
- Links to external websites

**Assessment:** Due to current hosting at SWM and unclear rights and role management → Magnolia excluded

### Liferay

**Description:** Digital Experience Platform (DXP) as On-Premise Subscription. Already in use at KM3 as an editorial content management system for the Personnel Service Portal (PSP), which manages personnel-relevant topics, content, and links.

**Functionalities:**

- Web Content Management System
- Document libraries and file management
- REST APIs
- Granular permission concept
- Tagging and categorization
- Self-hosted (on-premise)
- Customizable to specific requirements of case workers

**Assessment:** Liferay has high complexity and brings many dependencies and configuration requirements → Liferay excluded ("Simply too large")

### BlueSpice Wiki

**Description:** MediaWiki-based Enterprise Wiki System. Available via the central wiki server `wiki.muenchen.de`, where wikis are operated independently in their own system folders.

**Functionalities:**

- Independent creation, editing, and deletion of articles
- API (MediaWiki) for automated reading and change feed
- Document management, links, and categories
- Flexible rights/role concept
- Self-hosting on wiki.muenchen.de

**Assessment:** BlueSpice Wiki fundamentally meets all must-have requirements (MediaWiki API, flexible rights and role concept, categories, self-hosting) and is already in use at LHM.

### Zammad Knowledgebase

**Description:** Integrated knowledge base within the Zammad ticket system.

**Functionalities:**

- Native integration in Zammad
- Categorization of articles
- Rights and role concept
- Rich text editor for department
- Attachments and links
- API access via Zammad REST API (or EAI)
- RSS feed for change updates
- Export for backup via API access of individual categories possible

**Assessment:** The Zammad Knowledgebase meets the requirements. It is directly integrated into Zammad, easy to use for the department, and covers the must-have and nice-to-have requirements (API access, rights and role concept, document management, links).

## Overview

| Criterion         | Magnolia | Liferay | BlueSpice Wiki | Zammad KB |
| ----------------- | -------- | ------- | -------------- | --------- |
| Department Access | +        | +       | +              | ++        |
| API Interface     | +        | +       | +              | +         |
| Document Mgmt     | +        | +       | +              | +         |
| Rights/Roles      | ?        | +       | +              | +         |
| Backup/Export     | +        | +       | +              | +         |
| Low Maintenance   | -        | -       | o              | ++        |
| User Friendliness | o        | o       | +              | ++        |

## Decision Recommendation

After weighing the considered options, the Dev-Team favors the Zammad Knowledgebase.

**Rationale:**

- **Meets Requirements:** The Zammad Knowledgebase covers all central must-have requirements (API access, differentiated rights and role concept, document management, links) and offers useful additional features.
- **Best User Friendliness for Department:** Since the knowledgebase is directly available in the already-used Zammad interface, the department can create, edit, and maintain articles without additional systems. This reduces training effort and increases acceptance.
- **Minimal Operational Effort for the Dev-Team:** No new system needs to be introduced, operated, or maintained. Using the existing Zammad infrastructure reduces integration and operational costs.
- **Increased System Stability:** By integrating into the existing Zammad platform, no additional component is introduced that must be maintained separately or could fail. This minimizes potential error sources and increases overall system availability.
- **Simplified Reusability:** For other departments or organizations that want to use Zammad-AI, no additional component is required. The knowledgebase is already part of the Zammad installation, which considerably simplifies introduction and reuse.

**Challenges:**

- No automatic trigger for knowledgebase updates → _Solution:_ regular polling of differences via RSS feed
- Attached documents are not included when retrieving knowledge articles (Answers) → _Solution:_ Individual API calls to retrieve each document

**Conclusion:**

The Zammad Knowledgebase is the most practical and efficient solution for the requirements of this project and is recommended as the central knowledge platform.

## Decision made

In consultation with management, the Zammad Knowledgebase has been selected as the knowledge management system.
