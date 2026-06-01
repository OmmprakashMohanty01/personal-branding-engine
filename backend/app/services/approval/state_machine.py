class ApprovalStateMachine:
    """Enforces allowed state transitions for content drafts during the review lifecycle."""
    
    ALLOWED_TRANSITIONS = {
        "DRAFT": {"PENDING_APPROVAL", "APPROVED", "REJECTED"},
        "PENDING_APPROVAL": {"APPROVED", "REJECTED"},
        "REJECTED": {"PENDING_APPROVAL"},
        "APPROVED": set(), # Terminal status in the curation workflow
    }

    @classmethod
    def validate_transition(cls, current_status: str, target_status: str) -> None:
        """Validates if a draft can transition from current_status to target_status.
        
        Args:
            current_status: The current status of the draft.
            target_status: The desired status transition.
            
        Raises:
            ValueError: If the transition is disallowed by the state machine rules.
        """
        curr = current_status.upper()
        targ = target_status.upper()
        
        # Self-transitions are always allowed
        if curr == targ:
            return
            
        allowed = cls.ALLOWED_TRANSITIONS.get(curr, set())
        if targ not in allowed:
            raise ValueError(
                f"Disallowed state transition: Cannot change status from '{curr}' to '{targ}'."
            )
