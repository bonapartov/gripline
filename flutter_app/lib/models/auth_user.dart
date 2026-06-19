import 'package:equatable/equatable.dart';

class AuthUser extends Equatable {
  final String userId;
  final String username;
  final List<String> roles;
  final int? driverId;
  final int? teamId;
  final String token;

  const AuthUser({
    required this.userId,
    required this.username,
    required this.roles,
    this.driverId,
    this.teamId,
    required this.token,
  });

  bool get isPilot => roles.contains('pilot');
  bool get isManager => roles.contains('manager');

  factory AuthUser.fromJson(Map<String, dynamic> json, String token) {
    return AuthUser(
      userId: json['user_id'].toString(),
      username: json['username'] as String,
      roles: List<String>.from(json['roles'] ?? []),
      driverId: json['driver_id'] as int?,
      teamId: json['team_id'] as int?,
      token: token,
    );
  }

  @override
  List<Object?> get props => [userId, username, roles, driverId, teamId];
}
