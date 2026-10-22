using Xunit;

// Disable parallel test execution so benchmark memory measurements are isolated from concurrent test fixtures
[assembly: CollectionBehavior(DisableTestParallelization = true)]
