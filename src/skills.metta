(= (getSkills)
   (;INTERNAL:
    "- Remember a particular string such as skills and memories: remember string"
    "- Query long-term embedding memory for skills and memories with short phrases only: query string"
    "- Episodes searches history for episodes around a time stamp, time format is same as in TIME: episodes time_string"
    "- Pin a certain string as short-term working memory item to keep track of task state: pin string"
    ;SHELL AND FILE I/O:
    "- Execute shell command without apostrophe in string, it returns the command output to you: shell string"
    "- Read file to string: read-file filename"
    "- Write string to file: write-file filename string"
    "- Append line to file: append-file filename string",
    ;COMMUNICATION CHANNELS:
    "- Send message to user: send string"
    "- Search the web: search string"
    "- Search the web using the Tavily Search Agent: tavily-search string"
    "- Get technical analysis for a stock ticker using the Technical Analysis Agent: technical-analysis ticker"
    ;CODE EXECUTION:
    "- Execute MeTTa expression: metta sexpression"
    "Example to invoke Non-Axiomatic Logic via MeTTa: "
    "metta (|- ((--> (× sam garfield) friend) (stv 1.0 0.9))"
    "          ((--> garfield animal) (stv 1.0 0.9)))"
    "metta (|- ((==> (--> (× $1 elephant) eat) (--> $1 ([] dangerous))) (stv 1.0 0.9))"
    "          ((--> (× tiger elephant) eat) (stv 1.0 0.9)))"
    "Also: note the $1 for independent variables, and for negated knowledge use (stv 0.0 0.9)"
    "Additionally |- also works for revision, to merge evidence even when the term of both premises is the same."
    "You can also use PLN:"
    "metta (|~ ((Implication (Inheritance $1 (IntSet Feathered))"
    "           (Inheritance $1 Bird)) (stv 1.0 0.9))"
    "          ((Inheritance Pingu (IntSet Feathered)) (stv 1.0 0.9)))"
    ;BIO ATOMSPACE (BioCypher MeTTa exports):
    "- Index BioCypher output folder (build or reuse cache): bio-index"
    "- Force rebuild index from files: bio-reindex"
    "- Query the indexed atomspace (human-readable): bio-query \"command\""
    "  Commands: stats | folders | predicates | folder <group> | predicate <name> | node <type> <id> | entity <id> | help"
    "- Extract raw MeTTa atoms for symbolic injection: bio-extract \"command\""
    "  Same commands as bio-query. Output is raw s-expressions suitable for: metta (|- <atoms> <rule>)"
    "- Find shortest path between two entities (returns MeTTa edge atoms): bio-path \"src_id\" \"dst_id\""
    "  Example: bio-path \"ENSG00000125863\" \"CHEBI:15422\""
    "  Returns raw MeTTa atoms along the path, ready for symbolic reasoning."
    "Example neuro-symbolic reasoning chain:"
    "  1. bio-extract \"node gene ENSG00000125863\""
    "  2. Take the returned MeTTa atoms, inject into metta skill with an inference rule:"
    "     metta (|- (transcribes_to (gene ENSG00000125863) (transcript ENST0000353224))"
    "               (Inheritance ENSG00000125863 protein-coding-gene))"))

(= (read-file $file)
   (progn (translatePredicate (exists_file $file))
          (let $cmd (py-str ("cat '" $file "'"))
               (translatePredicate (shell $cmd $content)))
          $content))

(= (write-file $file $str)
   (progn (translatePredicate (open $file write $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (close $Out))
          WRITE-FILE-SUCCESS))

(= (append-file $file $str)
   (progn (translatePredicate (exists_file $file))
          (translatePredicate (open $file append $Out))
          (translatePredicate (write $Out $str))
          (translatePredicate (nl $Out)),
          (translatePredicate (close $Out))
          APPEND-FILE-SUCCESS))

(= (tavily-search $query)
   (py-call (agentverse.tavily_search $query)))

(= (technical-analysis $ticker)
   (py-call (agentverse.technical_analysis $ticker)))

; Bio atomspace skills — path is resolved dynamically via BIOCYPHER_KG_PATH env variable
(= (bio-index)
   (py-call (bio_graph.bio_index)))

(= (bio-reindex)
   (py-call (bio_graph.bio_reindex)))

(= (bio-query $q)
   (py-call (bio_graph.bio_query $q)))

(= (bio-extract $q)
   (py-call (bio_graph.bio_extract $q)))

(= (bio-path $src $dst)
   (py-call (bio_graph.bio_path $src $dst)))

!(import_prolog_functions_from_file (library OmegaClaw-Core ./src/skills.pl) (shell first_char gc read_file_tail))

(= (metta $str)
   (let $code (sread $str)
        (repr (swrite (eval $code)))))

(= (pin $x)
   PIN-SUCCESS)