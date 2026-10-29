{{/*
Framework >= 3.2.0 trust checks (KG trust anchors, hot-load, transcript
key). Same philosophy as ski.validate: fail the render loudly, not the Pod.
*/}}
{{- define "ski.validateTrust" -}}
{{- $anchors := .Values.kg.trustAnchors.configMapName -}}
{{- if and (not $anchors) (not .Values.kg.allowUnanchored) -}}
{{- fail "kg.trustAnchors.configMapName is required (SKI >= 3.2.0): a ConfigMap/Secret holding kg-trust-anchors.pem, the PEM bundle of Ed25519 public key(s) allowed to sign your Knowledge Graph. The runtime never trusts the key embedded in the KG. (Dev only, non-conformant: kg.allowUnanchored=true.)" -}}
{{- end -}}
{{- if and $anchors .Values.kg.allowUnanchored -}}
{{- fail "kg.allowUnanchored=true cannot be combined with kg.trustAnchors.configMapName: anchors are configured, so every KG must verify against them. Remove kg.allowUnanchored." -}}
{{- end -}}
{{- if and $anchors (eq $anchors .Values.kg.configMapName) -}}
{{- fail "kg.trustAnchors.configMapName must name a different object from kg.configMapName: whoever can change the KG must not also be able to change who may sign it." -}}
{{- end -}}
{{- if and (not .Values.skiModel.persistence.enabled) (not .Values.skiModel.transcriptKey.existingSecret) -}}
{{- fail "skiModel.persistence.enabled=false requires skiModel.transcriptKey.existingSecret: without a persistent or pre-provisioned transcript signing key the runtime would need a new key on every restart, and it refuses to start once the ledger holds signed transcripts." -}}
{{- end -}}
{{- end -}}
