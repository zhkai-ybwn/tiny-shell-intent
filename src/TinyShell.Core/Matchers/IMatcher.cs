using TinyShell.Core.Models;

namespace TinyShell.Core.Matchers;

public interface IMatcher
{
    List<Candidate> Match(string query, int topK = 3);
}
