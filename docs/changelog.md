# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Each revision is versioned by the date of the revision.

## 2026-02-02

- Add Java `custom_properties` configuration to charm config.

## 2026-01-11

- Remove agent number of relations limit.

## 2025-12-17

- Moved charm-architecture.md from Explanation to Reference category.

### 2025-12-02

- Add documentation on upgrading the charm.

### 2025-11-11

- Add missing outputs to the Terraform product module.

### 2025-09-29

- Terraform product module supports ingress, certificates, oauth2-proxy.

### 2025-09-23

- Support updated auth-proxy relation.

### 2025-09-18

- Fixed issue where naming the application deployment to "jenkins" would not add relation data with
    the agents.

### 2025-09-16

- Fix issue where the agents were not reconciled in previous revisions to reconcile on charm 
    upgrade.

### 2025-09-15

- Updated charm to use Noble base.

### 2025-09-10

- Added terraform module for charm and Jenkins product.
- Fix issue with service check which did not correctly report when service is ready for
    interaction.

### 2025-09-09

- Ejected deprecated `agent-deprecated`:`jenkins-slave` relation.

### 2025-09-05

- Fix issue with Jenkins agent node server discovery when ingress is applied to server.
- Fix race condition with agent trying to register before service ready.

### 2025-09-02

- Upgrade Jenkins version to latest LTS (v2.516.2).
- Upgrade Ubuntu base to Noble.

### 2025-05-01

- Added how-to landing page.

### 2025-04-01

- docs: changelog added.
