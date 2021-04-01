from typing import List, Iterator, Optional
from collections import namedtuple

import pandas as pd

from edi_835_parser.loops.claim import Claim as ClaimLoop
from edi_835_parser.loops.service import Service as ServiceLoop
from edi_835_parser.loops.organization import Organization as OrganizationLoop
from edi_835_parser.segments.utilities import find_identifier
from edi_835_parser.segments.interchange import Interchange as InterchangeSegment
from edi_835_parser.segments.financial_information import FinancialInformation as FinancialInformationSegment

BuildAttributeResponse = namedtuple('BuildAttributeResponse', 'key value segment segments')


class TransactionSet:

	def __init__(
			self,
			interchange: InterchangeSegment,
			financial_information: FinancialInformationSegment,
			claims: List[ClaimLoop],
			organizations: List[OrganizationLoop]
	):
		self.interchange = interchange
		self.financial_information = financial_information
		self.claims = claims
		self.organizations = organizations

	def __repr__(self):
		return '\n'.join(str(item) for item in self.__dict__.items())

	@property
	def payer(self) -> OrganizationLoop:
		payer = [o for o in self.organizations if o.organization.type == 'payer']
		assert len(payer) == 1
		return payer[0]

	def to_dataframe(self) -> pd.DataFrame:
		"""flatten the remittance advice by service to a pandas DataFrame"""
		data = []
		for claim in self.claims:
			for service in claim.services:

				serialized_service = TransactionSet.serialize_service(
					self.financial_information,
					self.payer,
					claim,
					service
				)

				datum = TransactionSet.add_line_item(serialized_service, service.service.paid_amount, 'payment', None, None)
				data.append(datum)

				for adjustment in service.adjustments:
					datum = TransactionSet.add_line_item(
						serialized_service,
						adjustment.amount,
						'adjustment',
						adjustment.group_code,
						adjustment.reason_code
					)
					data.append(datum)

		return pd.DataFrame(data)

	@staticmethod
	def add_line_item(
			service: dict,
			amount: int,
			type: str,
			group: Optional[str],
			reason: Optional[str]
	) -> dict:
		service = service.copy()

		service['amount'] = amount
		service['type'] = type
		service['group'] = group
		service['reason'] = reason

		return service

	@staticmethod
	def serialize_service(
			financial_information: FinancialInformationSegment,
			payer: OrganizationLoop,
			claim: ClaimLoop,
			service: ServiceLoop,
	) -> dict:
		remark = None
		if service.remark:
			remark = '{}: {}'.format(service.remark.qualifier, service.remark.code)

		reference = None
		if service.references:
			reference = ', '.join(str(r) for r in service.references)

		# if the service doesn't have a start date assume the service and claim dates match
		start_date = None
		if service.service_period_start:
			start_date = service.service_period_start.date
		elif claim.claim_statement_period_start:
			start_date = claim.claim_statement_period_start.date

		# if the service doesn't have an end date assume the service and claim dates match
		end_date = None
		if service.service_period_end:
			end_date = service.service_period_end.date
		elif claim.claim_statement_period_end:
			end_date = claim.claim_statement_period_end.date

		datum = {
			'claim_index': claim.claim.index,
			'patient': claim.patient.name,
			'code': service.service.service_code,
			'units': service.service.units,
			'transaction_date': financial_information.transaction_date,
			'charge_amount': service.service.charge_amount,
			'payer': payer.organization.name,
			'start_date': start_date,
			'end_date': end_date,
			'remark': remark,
			'reference': reference,
			'rendering_provider': claim.rendering_provider.name if claim.rendering_provider else None,
		}

		return datum

	@classmethod
	def build(cls, file_path: str) -> 'TransactionSet':
		interchange = None
		financial_information = None
		claims = []
		organizations = []

		with open(file_path) as f:
			file = f.read()

		segments = file.split('~')
		segments = [segment.strip() for segment in segments]

		segments = iter(segments)
		segment = None

		while True:
			response = cls.build_attribute(segment, segments)
			segment = response.segment
			segments = response.segments

			# no more segments to parse
			if response.segments is None:
				break

			if response.key == 'interchange':
				interchange = response.value

			if response.key == 'financial information':
				financial_information = response.value

			if response.key == 'organization':
				organizations.append(response.value)

			if response.key == 'claim':
				claims.append(response.value)

		return TransactionSet(interchange, financial_information, claims, organizations)

	@classmethod
	def build_attribute(cls, segment: Optional[str], segments: Iterator[str]) -> BuildAttributeResponse:
		if segment is None:
			try:
				segment = segments.__next__()
			except StopIteration:
				return BuildAttributeResponse(None, None, None, None)

		identifier = find_identifier(segment)

		if identifier == InterchangeSegment.identification:
			interchange = InterchangeSegment(segment)
			return BuildAttributeResponse('interchange', interchange, None, segments)

		if identifier == FinancialInformationSegment.identification:
			financial_information = FinancialInformationSegment(segment)
			return BuildAttributeResponse('financial information', financial_information, None, segments)

		if identifier == OrganizationLoop.initiating_identifier:
			organization, segments, segment = OrganizationLoop.build(segment, segments)
			return BuildAttributeResponse('organization', organization, segment, segments)

		elif identifier == ClaimLoop.initiating_identifier:
			claim, segments, segment = ClaimLoop.build(segment, segments)
			return BuildAttributeResponse('claim', claim, segment, segments)

		else:
			return BuildAttributeResponse(None, None, None, segments)


if __name__ == '__main__':
	pass