use serde::{Deserialize, Serialize};

use crate::Rank;

/// Table options agreed before the deal. Older snapshots without rules load
/// as the classic game.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(default, deny_unknown_fields)]
pub struct HouseRules {
    /// The ace counts below the two when deciding who holds the high card.
    /// The ace of spades still opens the first trick.
    pub ace_low: bool,
}

impl HouseRules {
    /// Strength used to decide the high card of a trick.
    pub fn strength(self, rank: Rank) -> u8 {
        match rank {
            Rank::Ace if self.ace_low => 0,
            _ => rank as u8 + 1,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ace_low_moves_only_the_ace() {
        let classic = HouseRules::default();
        let low = HouseRules { ace_low: true };
        assert!(classic.strength(Rank::Ace) > classic.strength(Rank::King));
        assert!(low.strength(Rank::Ace) < low.strength(Rank::Two));
        assert_eq!(low.strength(Rank::King), classic.strength(Rank::King));
    }
}
