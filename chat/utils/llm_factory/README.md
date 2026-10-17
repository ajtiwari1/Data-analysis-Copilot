# LLM factory

Place the provider-neutral LLM client interface, factory, and provider adapters in this
directory. Chat and agent code should depend on the shared interface rather than a
provider-specific SDK, allowing the configured backend provider to change without changing
chat routes or application logic.

Keep provider credentials server-side in environment configuration. Represent capabilities
such as streaming and tool/function calling explicitly, and report unsupported capabilities
as errors rather than silently degrading behavior.
