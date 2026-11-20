use std::collections::BTreeSet;

fn tokens(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|character: char| {
            !(character.is_alphanumeric() || matches!(character, '\u{0900}'..='\u{0D7F}'))
        })
        .filter(|word| !word.is_empty())
        .map(str::to_owned)
        .collect()
}

/// Rank passages with BM25. Documents without a matching term are omitted.
pub fn rank_passages(query: &str, passages: &[String]) -> Vec<usize> {
    let terms: BTreeSet<_> = tokens(query).into_iter().collect();
    let docs: Vec<_> = passages.iter().map(|text| tokens(text)).collect();
    if terms.is_empty() || docs.is_empty() {
        return Vec::new();
    }
    let average = (docs.iter().map(Vec::len).sum::<usize>() as f64 / docs.len() as f64).max(1.0);
    let mut scores = vec![0.0; docs.len()];
    for term in terms {
        let frequencies: Vec<_> = docs
            .iter()
            .map(|doc| doc.iter().filter(|token| **token == term).count() as f64)
            .collect();
        let found = frequencies
            .iter()
            .filter(|frequency| **frequency > 0.0)
            .count() as f64;
        let idf = (1.0 + (docs.len() as f64 - found + 0.5) / (found + 0.5)).ln();
        for (index, frequency) in frequencies.into_iter().enumerate() {
            let length = docs[index].len() as f64;
            scores[index] +=
                idf * (frequency * 2.2) / (frequency + 1.2 * (0.25 + 0.75 * length / average));
        }
    }
    let mut results: Vec<_> = (0..docs.len())
        .filter(|index| scores[*index] > 0.0)
        .collect();
    results.sort_by(|left, right| {
        scores[*right]
            .total_cmp(&scores[*left])
            .then(left.cmp(right))
    });
    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ranks_english_and_malayalam_and_omits_unmatched_passages() {
        let docs = vec![
            "ace opening card".to_owned(),
            "വെട്ട് Vettu cut pickup".to_owned(),
            "escape donkey".to_owned(),
        ];
        assert_eq!(rank_passages("വെട്ട്", &docs), [1]);
        assert_eq!(rank_passages("card", &docs), [0]);
        assert!(rank_passages("avocado", &docs).is_empty());
    }
}
